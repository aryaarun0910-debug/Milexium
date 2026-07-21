"""Train and validate demand models on REAL data, with conformal intervals.

Two models, same protocol as the synthetic pipeline (strict temporal
holdout, seasonal-naive baseline, count:poisson XGBoost):

1. NYC Access-A-Ride, borough-hour: actual paratransit bookings from the
   largest US paratransit operation, Jan 2024 to May 2026. This is the
   product's exact target variable on real data.
2. Chicago TNP, community-area-hour: 7+ years of real door-to-door trip
   demand (about 300M trips). Structurally the same forecasting problem at
   77-zone scale; proves the recipe holds on big real data.

Split per model, four non-overlapping 90-day-or-longer blocks so the
conformal calibration set is never touched by model fitting (using it for
both early stopping and calibration would forfeit the clean split-conformal
exchangeability guarantee):
  train  = everything before tune
  tune   = used ONLY as XGBoost's eval_set for early stopping
  cal    = used ONLY for conformal calibration, never seen during fit
  valid  = last 90 days, final reporting, never touched by fit or calibration
The seasonal-naive baseline gets train + tune + cal data (the generous,
honest choice). Conformal: Mondrian split-conformal, binned by predicted
decile, target 90 percent coverage; we report achieved coverage on the
untouched validation window.

Outputs: realdata/metrics_real.json, realdata/output/*.json models,
realdata/output/*_valid.csv.gz per-row validation predictions/intervals.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from pandas.tseries.holiday import USFederalHolidayCalendar
from sklearn.metrics import mean_absolute_error, r2_score

HERE = Path(__file__).parent
PANELS = HERE / "panels"
OUT = HERE / "output"
OUT.mkdir(exist_ok=True)

HOLIDAYS = USFederalHolidayCalendar().holidays(start="2018-01-01",
                                               end="2027-01-01")


def add_lags(df: pd.DataFrame, zone_col: str) -> pd.DataFrame:
    """Demand-history features, all available at day-ahead forecast time:
    same zone and hour 1, 7 and 14 days earlier, plus the trailing 28-day
    mean of that slot (shifted one day so nothing leaks)."""
    df = df.sort_values([zone_col, "hour", "date"])
    g = df.groupby([zone_col, "hour"], observed=True).y
    df["lag1"] = g.shift(1)
    df["lag7"] = g.shift(7)
    df["lag14"] = g.shift(14)
    df["roll28"] = df.groupby([zone_col, "hour"], observed=True).y.transform(
        lambda s: s.shift(1).rolling(28, min_periods=7).mean())
    return df


def add_calendar(df: pd.DataFrame) -> pd.DataFrame:
    df["date"] = pd.to_datetime(df.date)
    df["dow"] = df.date.dt.dayofweek
    df["month"] = df.date.dt.month
    df["is_weekend"] = (df.dow >= 5).astype(int)
    df["is_holiday"] = df.date.isin(HOLIDAYS).astype(int)
    df["hour_sin"] = np.sin(2 * np.pi * df.hour / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df.hour / 24)
    return df


def conformal(pred_cal, y_cal, pred, alpha=0.10, n_bins=10):
    """Mondrian split-conformal: per prediction-decile quantile of |resid|."""
    edges = np.quantile(pred_cal, np.linspace(0, 1, n_bins + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    resid = np.abs(y_cal - pred_cal)
    cal_bin = np.digitize(pred_cal, edges[1:-1])
    q = np.empty(n_bins)
    for b in range(n_bins):
        r = resid[cal_bin == b]
        # finite-sample corrected quantile
        k = min(len(r), int(np.ceil((len(r) + 1) * (1 - alpha))))
        q[b] = np.sort(r)[k - 1] if len(r) else np.nan
    bins = np.digitize(pred, edges[1:-1])
    width = q[bins]
    lo = np.clip(pred - width, 0, None)
    hi = pred + width
    return lo, hi


def conformal_two_way(pred_cal, y_cal, pred, hour_cal, hour_pred,
                       alpha=0.10, n_pred_bins=5, n_hour_buckets=4):
    """Two-way Mondrian split-conformal: bins jointly on hour-of-day bucket
    (demand is heteroskedastic by time of day beyond what the mean already
    captures, e.g. rush-hour absolute variance vs overnight) and prediction
    quintile within that bucket. Falls back to the single prediction-decile
    calibration for a sparse (hour-bucket, quintile) cell so a thin slice of
    calibration data never produces an unstable interval."""
    hour_bucket_cal = (hour_cal // (24 // n_hour_buckets)).astype(int)
    hour_bucket_pred = (hour_pred // (24 // n_hour_buckets)).astype(int)
    resid = np.abs(y_cal - pred_cal)

    # global fallback (single-dim decile) for thin cells
    g_edges = np.quantile(pred_cal, np.linspace(0, 1, n_pred_bins + 1))
    g_edges[0], g_edges[-1] = -np.inf, np.inf
    g_bin_cal = np.digitize(pred_cal, g_edges[1:-1])
    g_q = np.empty(n_pred_bins)
    for b in range(n_pred_bins):
        r = resid[g_bin_cal == b]
        k = min(len(r), int(np.ceil((len(r) + 1) * (1 - alpha))))
        g_q[b] = np.sort(r)[k - 1] if len(r) else np.nan

    MIN_CELL = 30
    q_table = {}
    edges_by_hb = {}
    for hb in range(n_hour_buckets):
        mask = hour_bucket_cal == hb
        pred_hb = pred_cal[mask]
        if mask.sum() < MIN_CELL * n_pred_bins:
            edges_by_hb[hb] = None
            continue
        edges = np.quantile(pred_hb, np.linspace(0, 1, n_pred_bins + 1))
        edges[0], edges[-1] = -np.inf, np.inf
        edges_by_hb[hb] = edges
        pbin = np.digitize(pred_hb, edges[1:-1])
        resid_hb = resid[mask]
        for b in range(n_pred_bins):
            r = resid_hb[pbin == b]
            if len(r) < MIN_CELL:
                q_table[(hb, b)] = None
                continue
            k = min(len(r), int(np.ceil((len(r) + 1) * (1 - alpha))))
            q_table[(hb, b)] = np.sort(r)[k - 1]

    width = np.empty(len(pred))
    for i in range(len(pred)):
        hb = hour_bucket_pred[i]
        edges = edges_by_hb.get(hb)
        w = None
        if edges is not None:
            pb = int(np.digitize(pred[i], edges[1:-1]))
            w = q_table.get((hb, pb))
        if w is None:
            gb = int(np.digitize(pred[i], g_edges[1:-1]))
            w = g_q[gb]
        width[i] = w
    lo = np.clip(pred - width, 0, None)
    hi = pred + width
    return lo, hi


def run(name, panel, zone_col, weather_city, extra_note):
    weather = pd.read_csv(PANELS / "weather_daily.csv", parse_dates=["date"])
    weather = weather[weather.city == weather_city].drop(columns=["city"])

    panel = add_calendar(panel)
    panel = add_lags(panel, zone_col)
    panel = panel.merge(weather, on="date", how="left")
    panel[zone_col] = panel[zone_col].astype("category")

    features = ["hour", "hour_sin", "hour_cos", "dow", "month", "is_weekend",
                "is_holiday", "tmax_c", "tmin_c", "precip_mm", "snow_cm",
                "lag1", "lag7", "lag14", "roll28", zone_col]

    d_max = panel.date.max()
    v0 = d_max - pd.Timedelta(days=90)
    c0 = v0 - pd.Timedelta(days=90)
    t0 = c0 - pd.Timedelta(days=90)
    train = panel[panel.date <= t0].dropna(subset=["lag14", "roll28"])
    tune = panel[(panel.date > t0) & (panel.date <= c0)]
    cal = panel[(panel.date > c0) & (panel.date <= v0)]
    valid = panel[panel.date > v0]

    model = xgb.XGBRegressor(
        n_estimators=600, max_depth=8, learning_rate=0.06,
        subsample=0.9, colsample_bytree=0.8, objective="count:poisson",
        random_state=42, n_jobs=-1, tree_method="hist",
        enable_categorical=True, early_stopping_rounds=30,
        eval_metric="poisson-nloglik")
    model.fit(train[features], train.y,
              eval_set=[(tune[features], tune.y)], verbose=False)

    pred_cal = model.predict(cal[features])
    pred = model.predict(valid[features])

    # Seasonal-naive: (zone, hour, dow) mean over train + tune + calibration
    hist = pd.concat([train, tune, cal])
    base = (hist.groupby([zone_col, "hour", "dow"], observed=True).y.mean()
            .rename("naive").reset_index())
    vb = valid.merge(base, how="left", on=[zone_col, "hour", "dow"])
    vb["naive"] = vb.naive.fillna(0)

    lo, hi = conformal(pred_cal, cal.y.to_numpy(), pred)
    covered = ((valid.y.to_numpy() >= lo) & (valid.y.to_numpy() <= hi))

    lo2, hi2 = conformal_two_way(
        pred_cal, cal.y.to_numpy(), pred,
        cal.hour.to_numpy(), valid.hour.to_numpy())
    covered2 = ((valid.y.to_numpy() >= lo2) & (valid.y.to_numpy() <= hi2))

    m = {
        "note": extra_note,
        "n_train": int(len(train)), "n_tune": int(len(tune)),
        "n_cal": int(len(cal)), "n_valid": int(len(valid)),
        "train_span": f"{panel.date.min().date()} to {t0.date()}",
        "tune_span": f"{t0.date()} to {c0.date()}",
        "cal_span": f"{c0.date()} to {v0.date()}",
        "valid_span": f"{v0.date()} to {d_max.date()}",
        "model_r2": round(float(r2_score(valid.y, pred)), 4),
        "model_mae": round(float(mean_absolute_error(valid.y, pred)), 4),
        "model_rmse": round(float(np.sqrt(np.mean((valid.y - pred) ** 2))), 4),
        "naive_r2": round(float(r2_score(vb.y, vb.naive)), 4),
        "naive_mae": round(float(mean_absolute_error(vb.y, vb.naive)), 4),
        "naive_rmse": round(float(np.sqrt(np.mean((vb.y - vb.naive) ** 2))), 4),
        "conformal_target_coverage": 0.90,
        "conformal_decile_only": {
            "achieved_coverage": round(float(covered.mean()), 4),
            "mean_interval_width": round(float((hi - lo).mean()), 3),
        },
        "conformal_hour_bucket_x_decile": {
            "achieved_coverage": round(float(covered2.mean()), 4),
            "mean_interval_width": round(float((hi2 - lo2).mean()), 3),
            "note": "Mondrian bins on (hour-of-day bucket, prediction "
                    "quintile within bucket); falls back to the "
                    "decile-only calibration for any bin with fewer than "
                    "30 calibration examples.",
        },
        "best_iteration": int(model.best_iteration),
    }

    model.save_model(OUT / f"{name}_model.json")
    v = valid[["date", "hour", zone_col, "y"]].copy()
    v["pred"] = pred
    v["lo"], v["hi"] = lo, hi
    v["lo_hourbucket"], v["hi_hourbucket"] = lo2, hi2
    v["naive"] = vb.naive.to_numpy()
    v.to_csv(OUT / f"{name}_valid.csv.gz", index=False, compression="gzip")
    return m


def load_aar():
    df = pd.read_csv(PANELS / "aar_hourly_borough.csv.gz")
    df = df[df.borough.isin(
        ["Bronx", "Brooklyn", "Manhattan", "Queens", "Staten Island"])]
    g = (df.groupby(["day", "hour", "borough"]).trips.sum()
         .rename("y").reset_index().rename(columns={"day": "date"}))
    # full grid including zero cells
    days = pd.date_range(g.date.min(), g.date.max(), freq="D")
    grid = pd.MultiIndex.from_product(
        [days, range(24), g.borough.unique()],
        names=["date", "hour", "borough"]).to_frame(index=False)
    grid["date"] = grid.date.dt.strftime("%Y-%m-%d")
    g["date"] = pd.to_datetime(g.date).dt.strftime("%Y-%m-%d")
    grid = grid.merge(g, how="left", on=["date", "hour", "borough"])
    grid["y"] = grid.y.fillna(0)
    return grid


def load_chicago():
    df = pd.read_csv(PANELS / "chicago_tnp_zone_hour.csv.gz")
    df = df.rename(columns={"trips": "y"})
    days = pd.date_range(df.date.min(), df.date.max(), freq="D")
    grid = pd.MultiIndex.from_product(
        [days, range(24), sorted(df.area.unique())],
        names=["date", "hour", "area"]).to_frame(index=False)
    grid["date"] = grid.date.dt.strftime("%Y-%m-%d")
    df["date"] = pd.to_datetime(df.date).dt.strftime("%Y-%m-%d")
    grid = grid.merge(df, how="left", on=["date", "hour", "area"])
    grid["y"] = grid.y.fillna(0)
    return grid


if __name__ == "__main__":
    results = {}

    results["nyc_access_a_ride"] = run(
        "aar", load_aar(), "borough", "nyc",
        "Real NYC Access-A-Ride paratransit bookings, borough-hour panel")
    print(json.dumps(results["nyc_access_a_ride"], indent=2))

    chi_path = PANELS / "chicago_tnp_zone_hour.csv.gz"
    if chi_path.exists():
        results["chicago_tnp"] = run(
            "chicago", load_chicago(), "area", "chicago",
            "Real Chicago TNP door-to-door trips, community-area-hour panel")
        print(json.dumps(results["chicago_tnp"], indent=2))
    else:
        print("chicago panel not downloaded yet, skipping")

    (HERE / "metrics_real.json").write_text(json.dumps(results, indent=2))
    print("saved realdata/metrics_real.json")
