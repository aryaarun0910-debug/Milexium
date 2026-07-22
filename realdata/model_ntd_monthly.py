"""Model nationwide NTD monthly demand-response demand, two ways.

Panel: realdata/panels/ntd_monthly_dr.csv.gz - 637 US agencies, monthly
unlinked passenger trips (UPT), vehicle revenue hours/miles, peak vehicles,
2002-2026. This is national paratransit DEMAND, which (as far as we can
tell) nobody models this way. Two evaluation protocols, because they answer
two different real questions:

  (A) TEMPORAL holdout - hold out the last HORIZON months across all
      agencies; train on everything strictly before. Answers: "for an
      agency we already serve, can we forecast the near future?"

  (B) HELD-OUT-AGENCY (cold start) - randomly hold out a fraction of
      agencies ENTIRELY; train on the rest. Predict the held-out agencies
      from their own filing history only, with NO agency-identity feature.
      Answers the actual onboarding question: "given a brand-new agency's
      public NTD filings and nothing else, can we forecast its demand?"
      This is the product's real cold-start problem, and it is the honest,
      hard test - most forecasting demos never run it.

Leakage discipline (feeds the point-in-time leakage audit): every feature
for target month t uses only information available at the end of month t-1.
UPT lags (t-1,2,3,12), a trailing 12-month UPT mean, and capacity
(VRH/VRM/VOMS) taken from t-1, never t. Calendar (month, year) is known.

Baseline: seasonal-naive = UPT of the same month one year earlier (the
natural monthly baseline). Every model number is reported against it.

Output: realdata/metrics_ntd_monthly.json
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, r2_score

HERE = Path(__file__).parent
PANEL = HERE / "panels" / "ntd_monthly_dr.csv.gz"
HORIZON = 12          # months held out for the temporal test
COLDSTART_FRAC = 0.20  # share of agencies held out entirely for cold start
SEED = 42

XGB = dict(n_estimators=700, max_depth=7, learning_rate=0.05,
           subsample=0.9, colsample_bytree=0.8, objective="count:poisson",
           random_state=SEED, tree_method="hist", device="cuda",
           eval_metric="poisson-nloglik", early_stopping_rounds=40)


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["ntd_id", "date"]).copy()
    df["date"] = pd.to_datetime(df.date)
    df["y"] = df.upt.astype(float)
    df["month"] = df.date.dt.month
    df["year"] = df.date.dt.year
    df["month_sin"] = np.sin(2 * np.pi * df.month / 12)
    df["month_cos"] = np.cos(2 * np.pi * df.month / 12)

    g = df.groupby("ntd_id", observed=True)
    # UPT history (all strictly past)
    for k in (1, 2, 3, 12):
        df[f"lag{k}"] = g.y.shift(k)
    df["roll12"] = g.y.transform(lambda s: s.shift(1).rolling(12, min_periods=6).mean())
    df["yoy_ratio"] = df.lag12 / df.roll12.replace(0, np.nan)
    # capacity from the PRIOR month (never the target month) - no leakage
    for col in ("vrh", "vrm", "voms"):
        df[f"{col}_lag1"] = g[col].shift(1)
    return df


FEATURES_FULL = ["month", "year", "month_sin", "month_cos",
                 "lag1", "lag2", "lag3", "lag12", "roll12", "yoy_ratio",
                 "vrh_lag1", "vrm_lag1", "voms_lag1", "ntd_id_cat"]
# cold start cannot use agency identity (unseen agencies)
FEATURES_COLD = [f for f in FEATURES_FULL if f != "ntd_id_cat"]


def naive(valid: pd.DataFrame) -> np.ndarray:
    # same month, one year earlier
    return valid.lag12.fillna(valid.roll12).fillna(0).to_numpy()


def score(name, y, pred, nai):
    return {
        "split": name,
        "n": int(len(y)),
        "model_r2": round(float(r2_score(y, pred)), 4),
        "model_mae": round(float(mean_absolute_error(y, pred)), 1),
        "naive_r2": round(float(r2_score(y, nai)), 4),
        "naive_mae": round(float(mean_absolute_error(y, nai)), 1),
        "model_mape": round(float(np.mean(np.abs((y - pred) / np.clip(y, 1, None)))), 4),
        "naive_mape": round(float(np.mean(np.abs((y - nai) / np.clip(y, 1, None)))), 4),
    }


def fit(train, valid, features):
    tr = train.dropna(subset=["lag12", "roll12"])
    va = valid.dropna(subset=["lag12", "roll12"])
    # temporal tune split off the tail of train for early stopping
    cut = tr.date.max() - pd.DateOffset(months=HORIZON)
    fit_tr = tr[tr.date <= cut]
    fit_tune = tr[tr.date > cut]
    if len(fit_tune) < 500:
        fit_tr, fit_tune = tr.iloc[:-500], tr.iloc[-500:]
    m = xgb.XGBRegressor(**XGB, enable_categorical=True)
    m.fit(fit_tr[features], fit_tr.y,
          eval_set=[(fit_tune[features], fit_tune.y)], verbose=False)
    pred = np.clip(m.predict(va[features]), 0, None)
    return m, va, pred


if __name__ == "__main__":
    raw = pd.read_csv(PANEL)
    df = build_features(raw)
    df["ntd_id_cat"] = df.ntd_id.astype("category")

    results = {"panel": {"agencies": int(df.ntd_id.nunique()),
                         "rows": int(len(df)),
                         "date_range": f"{df.date.min().date()} to {df.date.max().date()}",
                         "total_upt": int(df.y.sum())}}

    # ---- (A) temporal holdout ----
    d_max = df.date.max()
    v0 = d_max - pd.DateOffset(months=HORIZON)
    train_t = df[df.date <= v0]
    valid_t = df[df.date > v0]
    _, va, pred = fit(train_t, valid_t, FEATURES_FULL)
    results["temporal"] = score(f"temporal last {HORIZON}mo, all agencies, full features",
                                va.y.to_numpy(), pred, naive(va))
    print(json.dumps(results["temporal"], indent=2))

    # ---- (B) held-out-agency cold start ----
    rng = np.random.default_rng(SEED)
    agencies = df.ntd_id.unique()
    held = set(rng.choice(agencies, size=int(len(agencies) * COLDSTART_FRAC),
                          replace=False).tolist())
    train_c = df[~df.ntd_id.isin(held)]
    valid_c = df[df.ntd_id.isin(held)]
    # for cold start we still only fairly forecast the recent window of the
    # held-out agencies (their early history has no lags); use the last 24mo
    valid_c = valid_c[valid_c.date > d_max - pd.DateOffset(months=24)]
    _, va2, pred2 = fit(train_c, valid_c, FEATURES_COLD)
    results["cold_start_agency"] = score(
        f"held-out {len(held)} agencies ({COLDSTART_FRAC:.0%}), no agency identity",
        va2.y.to_numpy(), pred2, naive(va2))
    results["cold_start_agency"]["held_out_agencies"] = int(len(held))
    print(json.dumps(results["cold_start_agency"], indent=2))

    # feature importance from the temporal model for the write-up
    m_t, _, _ = fit(train_t, valid_t, FEATURES_FULL)
    imp = sorted(zip(FEATURES_FULL, m_t.feature_importances_.tolist()),
                 key=lambda t: -t[1])[:8]
    results["temporal_top_features"] = [[k, round(float(v), 4)] for k, v in imp]

    (HERE / "metrics_ntd_monthly.json").write_text(json.dumps(results, indent=2))
    print("\nsaved realdata/metrics_ntd_monthly.json")
    print(f"\nTEMPORAL:   model R2 {results['temporal']['model_r2']} vs "
          f"naive {results['temporal']['naive_r2']}")
    print(f"COLD-START: model R2 {results['cold_start_agency']['model_r2']} vs "
          f"naive {results['cold_start_agency']['naive_r2']}  "
          f"(forecasting agencies never seen in training)")
