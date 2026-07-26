"""Does weather actually help? An honest ablation: none vs daily vs hourly.

We committed real hourly weather (NOAA NCEI) but never proved it earns its
place as a feature. This is the test. Three AAR models on the SAME split,
same everything else, differing only in the weather feature set:

  none    - calendar + demand-history lags only
  daily   - + daily tmax/tmin/precip/snow (the current production feature)
  hourly  - + hourly temp/dewpoint/precip/wind/humidity for the target hour

Coverage honesty: the hourly panel (NOAA NCEI) runs through 2025-08, so the
ablation validates on a 90-day window ENDING inside that coverage (mid-2025),
not the production 2026 window. That is the correct, honest way to test
hourly weather - on data it actually covers - and it is stated plainly.

Prior expectation (from AAR SHAP): demand-history lags carry ~80% of the
signal, so weather is likely marginal. The ablation exists to confirm or
refute that with a number, not to assume it. CPU (small panel; leaves the
GPU free for other jobs).

Output: data/curated/metrics_weather_ablation.json
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, r2_score

HERE = Path(__file__).parent
from train_real_models import add_calendar, add_lags, load_aar  # noqa: E402

BASE = ["hour", "hour_sin", "hour_cos", "dow", "month", "is_weekend",
        "is_holiday", "lag1", "lag7", "lag14", "roll28", "borough"]
DAILY = ["tmax_c", "tmin_c", "precip_mm", "snow_cm"]
HOURLY = ["h_temp_c", "h_dewpoint_c", "h_precip_mm", "h_wind_kph", "h_humidity_pct"]

XGB = dict(n_estimators=500, max_depth=8, learning_rate=0.06, subsample=0.9,
           colsample_bytree=0.8, objective="count:poisson", random_state=42,
           tree_method="hist", enable_categorical=True,
           eval_metric="poisson-nloglik", early_stopping_rounds=30)


def prep():
    panel = add_lags(add_calendar(load_aar()), "borough")
    panel["date"] = pd.to_datetime(panel.date)
    # daily weather (nyc)
    wd = pd.read_csv(HERE / "panels" / "weather_daily.csv", parse_dates=["date"])
    wd = wd[wd.city == "nyc"].drop(columns=["city"])
    panel = panel.merge(wd, on="date", how="left")
    # hourly weather (nyc), keyed on date+hour
    wh = pd.read_csv(HERE / "panels" / "weather_hourly.csv.gz", parse_dates=["date"])
    wh = wh[wh.city == "nyc"].drop(columns=["city"]).rename(columns={
        "temp_c": "h_temp_c", "dewpoint_c": "h_dewpoint_c",
        "precip_mm": "h_precip_mm", "wind_kph": "h_wind_kph",
        "humidity_pct": "h_humidity_pct"})
    panel = panel.merge(wh, on=["date", "hour"], how="left")
    panel["borough"] = panel["borough"].astype("category")
    return panel


def run(panel, feats, tr, tu, va, nai):
    trc = tr.dropna(subset=feats + ["lag14", "roll28"])
    m = xgb.XGBRegressor(**XGB)
    m.fit(trc[feats], trc.y, eval_set=[(tu[feats], tu.y)], verbose=False)
    pred = np.clip(m.predict(va[feats]), 0, None)
    y = va.y.to_numpy()
    return {"model_r2": round(float(r2_score(y, pred)), 4),
            "model_mae": round(float(mean_absolute_error(y, pred)), 3),
            "naive_r2": round(float(r2_score(y, nai)), 4)}


if __name__ == "__main__":
    panel = prep()
    # validation window ends inside hourly-weather coverage (2025-08-25)
    hw_end = pd.Timestamp("2025-08-20")
    v0 = hw_end - pd.Timedelta(days=90)
    t0 = v0 - pd.Timedelta(days=90)
    tr = panel[panel.date <= t0]
    tu = panel[(panel.date > t0) & (panel.date <= v0)].dropna(subset=["lag14", "roll28"])
    va = panel[(panel.date > v0) & (panel.date <= hw_end)].dropna(subset=["lag14", "roll28"])
    base = pd.concat([tr, tu]).groupby(["borough", "hour", "dow"], observed=True).y.mean()
    nai = va.merge(base.rename("n").reset_index(), how="left",
                   on=["borough", "hour", "dow"]).n.fillna(0).to_numpy()

    results = {
        "note": "AAR, 90-day holdout ending 2025-08-20 (inside hourly-weather "
                "coverage). Weather feature ablation, all else identical.",
        "valid_window": f"{v0.date()} to {hw_end.date()}",
        "n_valid": int(len(va)),
        "hourly_weather_coverage_ends": "2025-08-25",
    }
    for label, feats in [("none", BASE), ("daily", BASE + DAILY),
                         ("hourly", BASE + HOURLY),
                         ("daily+hourly", BASE + DAILY + HOURLY)]:
        results[label] = run(panel, feats, tr, tu, va, nai)
        print(f"{label:14s}: R2 {results[label]['model_r2']} "
              f"MAE {results[label]['model_mae']}")

    (HERE / "metrics_weather_ablation.json").write_text(json.dumps(results, indent=2))
    print(f"\nnaive R2 {results['none']['naive_r2']} | saved metrics_weather_ablation.json")
