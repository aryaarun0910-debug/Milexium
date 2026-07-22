"""Count-distribution bake-off: is Poisson the right objective?

We have been training every model with count:poisson. Poisson assumes
variance == mean, which is often violated: zone-hour paratransit demand has
many zeros (over-dispersion / zero-inflation), and monthly agency UPT spans
hundreds to millions (massive over-dispersion). This script tests, honestly
and on the same clean temporal splits, whether a better-specified objective
beats Poisson.

Objectives compared (all native XGBoost except the hurdle model, which we
build as a real two-part model):
  - poisson            count:poisson (current default)
  - tweedie_1.1/1.3/1.5 reg:tweedie at three variance powers (compound
                        Poisson-Gamma: handles over-dispersion AND exact
                        zeros natively; the pragmatic stand-in for
                        negative-binomial / zero-inflated on count data)
  - gamma              reg:gamma (positive, over-dispersed; on y+1)
  - log_target         reg:squarederror on log1p(y), back-transformed
                        (log-normal-ish; tames a huge dynamic range)
  - hurdle             two-part: logistic P(y>0) times Poisson E[y|y>0].
                        A proper zero-inflated/hurdle model, meaningful only
                        where real zeros exist (the zone-hour panels).

True negative-binomial and full zero-inflated-Poisson need a custom XGBoost
objective (documented as a next step); Tweedie and the hurdle model cover
the same failure modes natively here, which is the honest pragmatic choice.

Every objective is scored against the SAME seasonal-naive baseline on the
SAME untouched validation window, so the comparison is like-for-like.

Output: realdata/metrics_objective_bakeoff.json
"""

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, r2_score

warnings.filterwarnings("ignore")
HERE = Path(__file__).parent

from train_real_models import add_calendar, add_lags, load_aar  # noqa: E402
from model_ntd_monthly import build_features, FEATURES_FULL     # noqa: E402

BASE = dict(n_estimators=500, max_depth=8, learning_rate=0.06,
            subsample=0.9, colsample_bytree=0.8, random_state=42,
            tree_method="hist", device="cuda", enable_categorical=True)


def metrics(y, pred, nai):
    return {
        "model_r2": round(float(r2_score(y, pred)), 4),
        "model_mae": round(float(mean_absolute_error(y, pred)), 3),
        "model_mape": round(float(np.mean(np.abs((y - pred) / np.clip(y, 1, None)))), 4),
        "naive_r2": round(float(r2_score(y, nai)), 4),
        "naive_mae": round(float(mean_absolute_error(y, nai)), 3),
    }


def fit_objective(obj, tr, tu, va, feats, y_naive):
    """Fit one objective, return metrics on the validation block."""
    ytr, ytu = tr.y.to_numpy(), tu.y.to_numpy()
    if obj == "poisson":
        m = xgb.XGBRegressor(**BASE, objective="count:poisson",
                             eval_metric="poisson-nloglik", early_stopping_rounds=30)
        m.fit(tr[feats], ytr, eval_set=[(tu[feats], ytu)], verbose=False)
        pred = np.clip(m.predict(va[feats]), 0, None)
    elif obj.startswith("tweedie"):
        vp = float(obj.split("_")[1])
        m = xgb.XGBRegressor(**BASE, objective="reg:tweedie",
                             tweedie_variance_power=vp,
                             eval_metric=f"tweedie-nloglik@{vp}",
                             early_stopping_rounds=30)
        m.fit(tr[feats], ytr, eval_set=[(tu[feats], ytu)], verbose=False)
        pred = np.clip(m.predict(va[feats]), 0, None)
    elif obj == "gamma":
        m = xgb.XGBRegressor(**BASE, objective="reg:gamma",
                             early_stopping_rounds=30)
        m.fit(tr[feats], ytr + 1, eval_set=[(tu[feats], ytu + 1)], verbose=False)
        pred = np.clip(m.predict(va[feats]) - 1, 0, None)
    elif obj == "log_target":
        m = xgb.XGBRegressor(**BASE, objective="reg:squarederror",
                             early_stopping_rounds=30)
        m.fit(tr[feats], np.log1p(ytr),
              eval_set=[(tu[feats], np.log1p(ytu))], verbose=False)
        pred = np.clip(np.expm1(m.predict(va[feats])), 0, None)
    elif obj == "hurdle":
        # part 1: P(y>0) logistic; part 2: Poisson on y|y>0
        clf = xgb.XGBClassifier(**BASE, objective="binary:logistic",
                                eval_metric="logloss", early_stopping_rounds=30)
        clf.fit(tr[feats], (ytr > 0).astype(int),
                eval_set=[(tu[feats], (ytu > 0).astype(int))], verbose=False)
        pos = tr[tr.y > 0]
        pos_tu = tu[tu.y > 0]
        reg = xgb.XGBRegressor(**BASE, objective="count:poisson",
                               eval_metric="poisson-nloglik", early_stopping_rounds=30)
        reg.fit(pos[feats], pos.y, eval_set=[(pos_tu[feats], pos_tu.y)], verbose=False)
        p_pos = clf.predict_proba(va[feats])[:, 1]
        rate = np.clip(reg.predict(va[feats]), 0, None)
        pred = p_pos * rate
    else:
        raise ValueError(obj)
    return metrics(va.y.to_numpy(), pred, y_naive)


def run_aar(objectives):
    panel = add_lags(add_calendar(load_aar()), "borough")
    panel["borough"] = panel["borough"].astype("category")
    feats = ["hour", "hour_sin", "hour_cos", "dow", "month", "is_weekend",
             "is_holiday", "lag1", "lag7", "lag14", "roll28", "borough"]
    d_max = panel.date.max()
    v0 = d_max - pd.Timedelta(days=90)
    t0 = v0 - pd.Timedelta(days=90)
    tr = panel[panel.date <= t0].dropna(subset=["lag14", "roll28"])
    tu = panel[(panel.date > t0) & (panel.date <= v0)]
    va = panel[panel.date > v0]
    base = pd.concat([tr, tu]).groupby(["borough", "hour", "dow"], observed=True).y.mean()
    nai = va.merge(base.rename("n").reset_index(), how="left",
                   on=["borough", "hour", "dow"]).n.fillna(0).to_numpy()
    frac0 = float((panel.y == 0).mean())
    out = {"panel": "AAR zone-hour", "pct_zero_cells": round(frac0, 3)}
    for o in objectives:
        out[o] = fit_objective(o, tr, tu, va, feats, nai)
        print(f"  AAR {o}: R2 {out[o]['model_r2']} MAE {out[o]['model_mae']}")
    return out


def run_ntd(objectives):
    df = build_features(pd.read_csv(HERE / "panels" / "ntd_monthly_dr.csv.gz"))
    df["ntd_id_cat"] = df.ntd_id.astype("category")
    feats = FEATURES_FULL
    d_max = df.date.max()
    v0 = d_max - pd.DateOffset(months=12)
    t0 = v0 - pd.DateOffset(months=12)
    tr = df[df.date <= t0].dropna(subset=["lag12", "roll12"])
    tu = df[(df.date > t0) & (df.date <= v0)].dropna(subset=["lag12", "roll12"])
    va = df[df.date > v0].dropna(subset=["lag12", "roll12"])
    nai = va.lag12.fillna(va.roll12).fillna(0).to_numpy()
    out = {"panel": "NTD monthly (all agencies)", "pct_zero_cells": round(float((df.y == 0).mean()), 3)}
    for o in objectives:
        out[o] = fit_objective(o, tr, tu, va, feats, nai)
        print(f"  NTD {o}: R2 {out[o]['model_r2']} MAE {out[o]['model_mae']} "
              f"MAPE {out[o]['model_mape']}")
    return out


if __name__ == "__main__":
    results = {}
    print("AAR zone-hour (has real zeros - hurdle meaningful):")
    results["aar"] = run_aar(["poisson", "tweedie_1.1", "tweedie_1.3",
                              "tweedie_1.5", "log_target", "hurdle"])
    print("NTD monthly (huge dynamic range - does Tweedie/log beat Poisson?):")
    results["ntd_monthly"] = run_ntd(["poisson", "tweedie_1.3", "tweedie_1.5",
                                      "gamma", "log_target"])
    (HERE / "metrics_objective_bakeoff.json").write_text(json.dumps(results, indent=2))
    print("\nsaved realdata/metrics_objective_bakeoff.json")
