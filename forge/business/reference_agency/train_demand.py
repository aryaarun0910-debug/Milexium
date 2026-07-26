"""Train the zone-hour demand model on the synthetic booking dataset.

Target: bookings per (zone, service hour, day). Validation is strictly
temporal (last 90 days held out) and reported against a seasonal-naive
baseline (mean bookings for the same zone/hour/day-of-week over the training
window), because R2 against zeros is easy and R2 against a calendar baseline
is the honest number.

Outputs: forge/business/reference_agency/output/demand_model.json, metrics.json,
panel_valid.csv
"""

import json
import numpy as np
import pandas as pd
import xgboost as xgb
from pathlib import Path
from sklearn.metrics import mean_absolute_error, r2_score

OUT = Path(__file__).parent / "output"
trips = pd.read_csv(OUT / "trips.csv", parse_dates=["date"])
zones = pd.read_csv(OUT / "zones.csv")
weather = pd.read_csv(OUT / "weather.csv", parse_dates=["date"])

HOLIDAYS = pd.to_datetime([
    "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25", "2026-01-01",
    "2026-01-19", "2026-05-25", "2026-06-19",
])

# Demand = all bookings (cancelled trips were still demand on the system)
agg = (trips.groupby(["date", "hour", "origin_zone"]).size()
       .rename("bookings").reset_index())

# Full panel including zero cells: every date x hour 5-21 x zone
dates = pd.date_range(trips.date.min(), trips.date.max(), freq="D")
panel = pd.MultiIndex.from_product(
    [dates, range(5, 22), zones.zone_id],
    names=["date", "hour", "origin_zone"]).to_frame(index=False)
panel = panel.merge(agg, how="left", on=["date", "hour", "origin_zone"])
panel["bookings"] = panel.bookings.fillna(0).astype(int)

panel["dow"] = panel.date.dt.dayofweek
panel["month"] = panel.date.dt.month
panel["is_weekend"] = (panel.dow >= 5).astype(int)
panel["is_holiday"] = panel.date.isin(HOLIDAYS).astype(int)
panel["hour_sin"] = np.sin(2 * np.pi * panel.hour / 24)
panel["hour_cos"] = np.cos(2 * np.pi * panel.hour / 24)
panel = panel.merge(weather, on="date").merge(
    zones, left_on="origin_zone", right_on="zone_id")

FEATURES = ["hour", "hour_sin", "hour_cos", "dow", "month", "is_weekend",
            "is_holiday", "temp_c", "precip_mm", "pop_density",
            "share_over_65", "has_medical", "has_dialysis", "has_daycenter",
            "gx", "gy"]

split = panel.date.max() - pd.Timedelta(days=90)
train, valid = panel[panel.date <= split], panel[panel.date > split]

model = xgb.XGBRegressor(
    n_estimators=500, max_depth=6, learning_rate=0.06,
    subsample=0.9, colsample_bytree=0.8, objective="count:poisson",
    random_state=42, n_jobs=-1, early_stopping_rounds=30,
    eval_metric="poisson-nloglik")
model.fit(train[FEATURES], train.bookings,
          eval_set=[(valid[FEATURES], valid.bookings)], verbose=False)

pred = model.predict(valid[FEATURES])

# Seasonal-naive baseline: train-window mean per (zone, hour, dow)
base = (train.groupby(["origin_zone", "hour", "dow"]).bookings.mean()
        .rename("naive").reset_index())
vb = valid.merge(base, how="left", on=["origin_zone", "hour", "dow"])
vb["naive"] = vb.naive.fillna(0)

metrics = {
    "n_train": int(len(train)), "n_valid": int(len(valid)),
    "split_date": str(split.date()),
    "model_r2": round(float(r2_score(valid.bookings, pred)), 4),
    "model_mae": round(float(mean_absolute_error(valid.bookings, pred)), 4),
    "model_rmse": round(float(np.sqrt(np.mean((valid.bookings - pred) ** 2))), 4),
    "naive_r2": round(float(r2_score(vb.bookings, vb.naive)), 4),
    "naive_mae": round(float(mean_absolute_error(vb.bookings, vb.naive)), 4),
    "naive_rmse": round(float(np.sqrt(np.mean((vb.bookings - vb.naive) ** 2))), 4),
    "best_iteration": int(model.best_iteration),
}
imp = sorted(zip(FEATURES, model.feature_importances_.round(4).tolist()),
             key=lambda t: -t[1])
metrics["feature_importance"] = imp[:10]

model.save_model(OUT / "demand_model.json")
valid_out = valid.copy()
valid_out["pred"] = pred
valid_out.to_csv(OUT / "panel_valid.csv", index=False)
(OUT / "metrics.json").write_text(json.dumps(metrics, indent=2))
print(json.dumps(metrics, indent=2))
