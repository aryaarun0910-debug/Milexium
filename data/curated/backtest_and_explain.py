"""Walk-forward backtest and SHAP explainability on the real demand models.

Two additions beyond train_real_models.py's single 90-day holdout:

1. Rolling-origin backtest: 4 non-overlapping 90-day folds walking back
   from the most recent data, each with its own model trained on an
   EXPANDING window of everything strictly before that fold (no peeking,
   no fixed-size train set shrinking the earliest fold). Reports R2/MAE
   per fold plus mean and std across folds, because a single lucky holdout
   window is a weak claim and four consistent folds is a strong one.

2. SHAP explainability: TreeExplainer on the production model (the one
   train_real_models.py already saved), applied to the most recent
   holdout. Produces (a) global feature importance by mean |SHAP| and
   (b) a handful of worked "why this forecast" examples in the same
   plain-language format the product's explanation cards use, generated
   from a REAL model on REAL data rather than illustrative copy.

Run after train_real_models.py. Outputs:
  data/curated/backtest_<name>.json
  data/curated/explanations_<name>.json
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import shap
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, r2_score

from train_real_models import add_calendar, add_lags, load_aar, load_chicago

HERE = Path(__file__).parent
PANELS = HERE / "panels"
OUT = HERE / "output"

FEATURES = ["hour", "hour_sin", "hour_cos", "dow", "month", "is_weekend",
            "is_holiday", "tmax_c", "tmin_c", "precip_mm", "snow_cm",
            "lag1", "lag7", "lag14", "roll28"]

FEATURE_LABELS = {
    "hour": "time of day", "hour_sin": "time of day", "hour_cos": "time of day",
    "dow": "day of week", "month": "month of year",
    "is_weekend": "weekend", "is_holiday": "holiday",
    "tmax_c": "forecast high temperature", "tmin_c": "forecast low temperature",
    "precip_mm": "forecast rainfall", "snow_cm": "forecast snowfall",
    "lag1": "yesterday's bookings in this slot",
    "lag7": "same day last week", "lag14": "same day two weeks ago",
    "roll28": "28-day average for this slot",
}


def prep(panel, zone_col, weather_city):
    weather = pd.read_csv(PANELS / "weather_daily.csv", parse_dates=["date"])
    weather = weather[weather.city == weather_city].drop(columns=["city"])
    panel = add_calendar(panel)
    panel = add_lags(panel, zone_col)
    panel = panel.merge(weather, on="date", how="left")
    panel[zone_col] = panel[zone_col].astype("category")
    return panel


def fit(train, features):
    model = xgb.XGBRegressor(
        n_estimators=400, max_depth=8, learning_rate=0.08,
        subsample=0.9, colsample_bytree=0.8, objective="count:poisson",
        random_state=42, n_jobs=-1, tree_method="hist",
        enable_categorical=True)
    model.fit(train[features], train.y)
    return model


def walk_forward(panel, zone_col, name, n_folds=4, fold_days=90):
    features = FEATURES + [zone_col]
    d_max = panel.date.max()
    folds = []
    for i in range(n_folds):
        v1 = d_max - pd.Timedelta(days=i * fold_days)
        v0 = d_max - pd.Timedelta(days=(i + 1) * fold_days)
        train = panel[panel.date <= v0].dropna(subset=["lag14", "roll28"])
        valid = panel[(panel.date > v0) & (panel.date <= v1)]
        if len(train) < 1000 or len(valid) < 100:
            continue
        model = fit(train, features)
        pred = model.predict(valid[features])
        base = (train.groupby([zone_col, "hour", "dow"], observed=True).y
                .mean().rename("naive").reset_index())
        vb = valid.merge(base, how="left", on=[zone_col, "hour", "dow"])
        vb["naive"] = vb.naive.fillna(0)
        folds.append({
            "fold": i, "valid_span": f"{v0.date()} to {v1.date()}",
            "n_train": int(len(train)), "n_valid": int(len(valid)),
            "model_r2": round(float(r2_score(valid.y, pred)), 4),
            "model_mae": round(float(mean_absolute_error(valid.y, pred)), 4),
            "naive_r2": round(float(r2_score(vb.y, vb.naive)), 4),
            "naive_mae": round(float(mean_absolute_error(vb.y, vb.naive)), 4),
        })
    r2s = [f["model_r2"] for f in folds]
    naive_r2s = [f["naive_r2"] for f in folds]
    result = {
        "note": f"Rolling-origin backtest, {name}, expanding training window, "
                f"{fold_days}-day non-overlapping folds walking back from "
                f"the most recent data",
        "folds": folds,
        "model_r2_mean": round(float(np.mean(r2s)), 4),
        "model_r2_std": round(float(np.std(r2s)), 4),
        "naive_r2_mean": round(float(np.mean(naive_r2s)), 4),
        "naive_r2_std": round(float(np.std(naive_r2s)), 4),
    }
    (HERE / f"backtest_{name}.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return result


def explain(panel, zone_col, name, n_examples=6):
    features = FEATURES + [zone_col]
    d_max = panel.date.max()
    v0 = d_max - pd.Timedelta(days=90)
    c0 = v0 - pd.Timedelta(days=90)
    train = panel[panel.date <= c0].dropna(subset=["lag14", "roll28"])
    valid = panel[panel.date > v0].reset_index(drop=True)

    model = xgb.Booster()
    model.load_model(OUT / f"{name}_model.json")

    # SHAP operates in margin (log-rate) space for a poisson-link model:
    # sign and relative rank of a contribution are still valid (the log
    # link is monotonic), but contributions do not sum linearly in count
    # units, so we use them for direction and ranking, not arithmetic.
    explainer = shap.TreeExplainer(model)
    dm = xgb.DMatrix(valid[features], enable_categorical=True)
    shap_values = explainer.shap_values(dm)
    base_rate = float(np.exp(explainer.expected_value))
    pred = model.predict(dm)

    global_imp = (pd.Series(np.abs(shap_values).mean(axis=0), index=features)
                  .sort_values(ascending=False))
    global_imp_out = {k: round(float(v), 4) for k, v in global_imp.items()}

    rng = np.random.default_rng(42)
    busy = valid.y[valid.y > valid.y.quantile(0.7)].index
    idx = rng.choice(busy, size=min(n_examples, len(busy)), replace=False)

    examples = []
    for i in idx:
        row = valid.iloc[i]
        sv = shap_values[i]
        order = np.argsort(-np.abs(sv))[:4]
        factors = []
        for j in order:
            feat = features[j]
            label = FEATURE_LABELS.get(feat, feat)
            direction = "raised" if sv[j] > 0 else "lowered"
            factors.append({
                "feature": feat, "label": label,
                "value": (str(row[feat]) if feat == zone_col
                          else round(float(row[feat]), 2)),
                "shap": round(float(sv[j]), 4),
                "direction": direction,
            })
        examples.append({
            "date": str(row.date.date()), "hour": int(row.hour),
            "zone": str(row[zone_col]), "actual_bookings": int(row.y),
            "predicted_bookings": round(float(pred[i]), 1),
            "base_rate": round(base_rate, 2),
            "top_factors": factors,
            "explanation": (
                f"Predicted {pred[i]:.0f} bookings for {row[zone_col]} at "
                f"{int(row.hour):02d}:00 on {row.date.date()}. Baseline rate "
                f"is {base_rate:.1f}; " +
                "; ".join(f"{f['label']} {f['direction']} the estimate"
                          for f in factors) + "."),
        })

    result = {
        "note": f"SHAP TreeExplainer on the production {name} model, "
                f"validation window {v0.date()} to {d_max.date()}",
        "global_feature_importance_mean_abs_shap": global_imp_out,
        "example_explanations": examples,
    }
    (HERE / f"explanations_{name}.json").write_text(json.dumps(result, indent=2))
    print(f"saved data/curated/explanations_{name}.json, "
          f"top feature: {global_imp.index[0]}")
    return result


if __name__ == "__main__":
    aar = prep(load_aar(), "borough", "nyc")
    walk_forward(aar, "borough", "aar")
    explain(aar, "borough", "aar")

    chi_path = PANELS / "chicago_tnp_zone_hour.csv.gz"
    if chi_path.exists() and (OUT / "chicago_model.json").exists():
        chi = prep(load_chicago(), "area", "chicago")
        walk_forward(chi, "area", "chicago")
        explain(chi, "area", "chicago")
    else:
        print("chicago model/panel not ready yet, skipping")
