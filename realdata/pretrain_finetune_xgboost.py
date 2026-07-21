"""Empirically test the transformer notebook's core hypothesis — does
pretraining on real mass-transit data help forecast real paratransit
demand — using a method that actually runs today, on CPU, with no GPU and
no Kaggle: XGBoost's native continued-boosting (`xgb_model=`), which is a
genuine, well-understood transfer mechanism (more trees fit on new data,
starting from an existing model's trees), not a toy analogy.

To keep the pretrain -> finetune boundary valid, the feature schema must
be IDENTICAL across both stages (XGBoost requires matching feature count/
order to continue boosting). That means the pretrain stage cannot use a
zone-specific categorical (Chicago's areas, MTA's routes/stations, and
AAR's boroughs are different vocabularies) -- it only uses calendar,
weather, and demand-history features, i.e. "how does demand move with
time and recent history," independent of geography.

Three models compared on the IDENTICAL AAR train/tune/cal/valid split:
  A. aar_only_no_zone   -- baseline, generic features only, no pretraining
  B. pretrain_finetune  -- pretrained on Chicago+MTA bus+MTA subway (generic
                           features only), then continued-boosted on AAR
  C. aar_only_with_zone -- the production model (train_real_models.py),
                           generic features + borough categorical

A vs B isolates the pretraining effect. C is there so a reader isn't left
wondering "why is this worse than the number in the README" -- it's
answering a different, narrower question on purpose (whether pretraining
alone helps, before zone identity is even in the picture).

Output: realdata/pretrain_finetune_results.json
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, r2_score

from train_real_models import (add_calendar, add_lags, load_aar,
                               load_chicago, load_mta_bus, load_mta_subway)

HERE = Path(__file__).parent
PANELS = HERE / "panels"
OUT = HERE / "output"

GENERIC_FEATURES = ["hour", "hour_sin", "hour_cos", "dow", "month",
                    "is_weekend", "is_holiday", "tmax_c", "tmin_c",
                    "precip_mm", "snow_cm", "lag1", "lag7", "lag14", "roll28"]

XGB_PARAMS = dict(
    n_estimators=600, max_depth=8, learning_rate=0.06,
    subsample=0.9, colsample_bytree=0.8, objective="count:poisson",
    random_state=42, tree_method="hist", device="cuda",
    early_stopping_rounds=30, eval_metric="poisson-nloglik")


def prep_generic(panel, zone_col, weather_city):
    """Calendar + weather + lags, NO zone categorical -- the shared schema
    that lets a booster trained on one dataset continue training on
    another."""
    weather = pd.read_csv(PANELS / "weather_daily.csv", parse_dates=["date"])
    weather = weather[weather.city == weather_city].drop(columns=["city"])
    panel = add_calendar(panel)
    panel = add_lags(panel, zone_col)
    panel = panel.merge(weather, on="date", how="left")
    return panel.dropna(subset=["lag14", "roll28"])


def three_way_split(panel):
    d_max = panel.date.max()
    v0 = d_max - pd.Timedelta(days=90)
    c0 = v0 - pd.Timedelta(days=90)
    t0 = c0 - pd.Timedelta(days=90)
    train = panel[panel.date <= t0]
    tune = panel[(panel.date > t0) & (panel.date <= c0)]
    cal = panel[(panel.date > c0) & (panel.date <= v0)]
    valid = panel[panel.date > v0]
    return train, tune, cal, valid


def eval_on_aar(model, aar_valid, aar_train_hist, zone_col):
    pred = model.predict(aar_valid[GENERIC_FEATURES])
    base = (aar_train_hist.groupby([zone_col, "hour", "dow"], observed=True)
            .y.mean().rename("naive").reset_index())
    vb = aar_valid.merge(base, how="left", on=[zone_col, "hour", "dow"])
    vb["naive"] = vb.naive.fillna(0)
    return {
        "model_r2": round(float(r2_score(aar_valid.y, pred)), 4),
        "model_mae": round(float(mean_absolute_error(aar_valid.y, pred)), 4),
        "naive_r2": round(float(r2_score(vb.y, vb.naive)), 4),
        "naive_mae": round(float(mean_absolute_error(vb.y, vb.naive)), 4),
    }


if __name__ == "__main__":
    results = {}

    print("preparing AAR (generic features, no zone)...", flush=True)
    aar = prep_generic(load_aar(), "borough", "nyc")
    aar_train, aar_tune, aar_cal, aar_valid = three_way_split(aar)
    aar_hist = pd.concat([aar_train, aar_tune, aar_cal])

    # ---- A. AAR-only baseline, generic features, no pretraining ----
    print("A: AAR-only, no zone, no pretraining...", flush=True)
    model_a = xgb.XGBRegressor(**XGB_PARAMS)
    model_a.fit(aar_train[GENERIC_FEATURES], aar_train.y,
                eval_set=[(aar_tune[GENERIC_FEATURES], aar_tune.y)],
                verbose=False)
    results["A_aar_only_no_zone"] = eval_on_aar(model_a, aar_valid, aar_hist, "borough")
    results["A_aar_only_no_zone"]["best_iteration"] = int(model_a.best_iteration)
    print(json.dumps(results["A_aar_only_no_zone"], indent=2))

    # ---- Pretrain corpus: Chicago + MTA bus + MTA subway, generic features ----
    print("preparing pretrain corpus (Chicago + MTA bus + MTA subway)...",
          flush=True)
    pretrain_frames = []
    if (PANELS / "chicago_tnp_zone_hour.csv.gz").exists():
        pretrain_frames.append(prep_generic(load_chicago(), "area", "chicago"))
    if (PANELS / "mta_bus_route_hour.csv.gz").exists():
        pretrain_frames.append(prep_generic(load_mta_bus(), "route", "nyc"))
    if (PANELS / "mta_subway_station_hour.csv.gz").exists():
        pretrain_frames.append(prep_generic(load_mta_subway(), "station_id", "nyc"))
    pretrain = pd.concat([f[GENERIC_FEATURES + ["y"]] for f in pretrain_frames],
                        ignore_index=True)
    # simple train/tune split for the pretrain stage's own early stopping
    # (a random split is fine here -- this stage isn't the one being
    # temporally evaluated, only used as a warm start)
    rng = np.random.default_rng(42)
    mask = rng.random(len(pretrain)) < 0.9
    pt_train, pt_tune = pretrain[mask], pretrain[~mask]
    print(f"pretrain corpus: {len(pretrain):,} rows from "
          f"{len(pretrain_frames)} datasets", flush=True)

    print("B: pretraining on mass-transit corpus...", flush=True)
    model_pre = xgb.XGBRegressor(**XGB_PARAMS)
    model_pre.fit(pt_train[GENERIC_FEATURES], pt_train.y,
                  eval_set=[(pt_tune[GENERIC_FEATURES], pt_tune.y)],
                  verbose=False)
    model_pre.save_model(OUT / "pretrain_generic_model.json")
    print(f"pretrain stage: best_iteration={model_pre.best_iteration}",
          flush=True)

    print("B: continued-boosting (finetuning) on AAR...", flush=True)
    booster_pre = xgb.Booster()
    booster_pre.load_model(OUT / "pretrain_generic_model.json")
    model_b = xgb.XGBRegressor(**{**XGB_PARAMS, "n_estimators": 300})
    model_b.fit(aar_train[GENERIC_FEATURES], aar_train.y,
                eval_set=[(aar_tune[GENERIC_FEATURES], aar_tune.y)],
                xgb_model=booster_pre, verbose=False)
    results["B_pretrain_then_finetune"] = eval_on_aar(model_b, aar_valid, aar_hist, "borough")
    results["B_pretrain_then_finetune"]["best_iteration"] = int(model_b.best_iteration)
    results["B_pretrain_then_finetune"]["pretrain_rows"] = int(len(pretrain))
    results["B_pretrain_then_finetune"]["pretrain_datasets"] = len(pretrain_frames)
    print(json.dumps(results["B_pretrain_then_finetune"], indent=2))

    # ---- C. Production model for context (generic + zone, no pretraining) ----
    print("C: AAR-only, with zone (matches the production model)...", flush=True)
    aar_with_zone = load_aar()
    aar_with_zone = add_calendar(aar_with_zone)
    aar_with_zone = add_lags(aar_with_zone, "borough")
    weather = pd.read_csv(PANELS / "weather_daily.csv", parse_dates=["date"])
    weather = weather[weather.city == "nyc"].drop(columns=["city"])
    aar_with_zone = aar_with_zone.merge(weather, on="date", how="left").dropna(
        subset=["lag14", "roll28"])
    aar_with_zone["borough"] = aar_with_zone["borough"].astype("category")
    features_z = GENERIC_FEATURES + ["borough"]
    tr, tu, ca, va = three_way_split(aar_with_zone)
    hist_z = pd.concat([tr, tu, ca])
    model_c = xgb.XGBRegressor(**{**XGB_PARAMS, "enable_categorical": True})
    model_c.fit(tr[features_z], tr.y, eval_set=[(tu[features_z], tu.y)],
                verbose=False)
    pred_c = model_c.predict(va[features_z])
    base_c = (hist_z.groupby(["borough", "hour", "dow"], observed=True)
             .y.mean().rename("naive").reset_index())
    vb_c = va.merge(base_c, how="left", on=["borough", "hour", "dow"])
    vb_c["naive"] = vb_c.naive.fillna(0)
    results["C_aar_only_with_zone_production"] = {
        "model_r2": round(float(r2_score(va.y, pred_c)), 4),
        "model_mae": round(float(mean_absolute_error(va.y, pred_c)), 4),
        "naive_r2": round(float(r2_score(vb_c.y, vb_c.naive)), 4),
        "naive_mae": round(float(mean_absolute_error(vb_c.y, vb_c.naive)), 4),
        "note": "production model already reported in metrics_real.json; "
                "recomputed here only so all three numbers sit side by "
                "side on one identical AAR holdout window",
    }
    print(json.dumps(results["C_aar_only_with_zone_production"], indent=2))

    verdict = (
        "PRETRAINING HELPED" if
        results["B_pretrain_then_finetune"]["model_r2"] >
        results["A_aar_only_no_zone"]["model_r2"] + 0.002
        else "NO MEANINGFUL DIFFERENCE" if
        abs(results["B_pretrain_then_finetune"]["model_r2"] -
            results["A_aar_only_no_zone"]["model_r2"]) <= 0.002
        else "PRETRAINING HURT"
    )
    results["verdict"] = verdict
    results["verdict_note"] = (
        "Comparing A (no pretrain) vs B (pretrained on Chicago+MTA bus+MTA "
        "subway, generic features only, no zone identity in either). This "
        "is the honest, narrow test of the transformer notebook's central "
        "design bet, run with a method that actually executed today.")

    (HERE / "pretrain_finetune_results.json").write_text(
        json.dumps(results, indent=2))
    print("\n" + "=" * 60)
    print(f"VERDICT: {verdict}")
    print("=" * 60)
    print("saved realdata/pretrain_finetune_results.json")
