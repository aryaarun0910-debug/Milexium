"""Control for the transfer experiment: is B's gain transfer or just more trees?

B (pretrain+finetune) beat A (AAR-only) 0.9913 vs 0.9862. But continued-
boosting means B has more total trees. Give AAR-only the same (and larger)
tree budgets and see if it closes the gap. If AAR-only-with-more-trees
reaches ~0.991, the gain was capacity, not transfer.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, r2_score

sys.path.insert(0, str(Path("realdata")))
from train_real_models import add_calendar, add_lags, load_aar

GF = ["hour", "hour_sin", "hour_cos", "dow", "month", "is_weekend",
      "is_holiday", "tmax_c", "tmin_c", "precip_mm", "snow_cm",
      "lag1", "lag7", "lag14", "roll28"]

w = pd.read_csv("realdata/panels/weather_daily.csv", parse_dates=["date"])
w = w[w.city == "nyc"].drop(columns=["city"])
p = add_lags(add_calendar(load_aar()), "borough").merge(w, on="date", how="left")
p = p.dropna(subset=["lag14", "roll28"])
d_max = p.date.max()
v0, c0 = d_max - pd.Timedelta(days=90), d_max - pd.Timedelta(days=180)
t0 = c0 - pd.Timedelta(days=90)
tr, tu, va = p[p.date <= t0], p[(p.date > t0) & (p.date <= c0)], p[p.date > v0]
y = va.y.to_numpy()

for n in (400, 750, 1200, 2000):
    m = xgb.XGBRegressor(n_estimators=n, max_depth=8, learning_rate=0.06,
                         subsample=0.9, colsample_bytree=0.8,
                         objective="count:poisson", random_state=42,
                         tree_method="hist", device="cuda")
    m.fit(tr[GF], tr.y, verbose=False)
    pred = np.clip(m.predict(va[GF]), 0, None)
    print(f"AAR-only, {n} trees (no early stop): R2 {r2_score(y, pred):.4f} "
          f"MAE {mean_absolute_error(y, pred):.2f}")
print("(B pretrain+finetune was R2 0.9913 / MAE 17.18; A early-stopped was 0.9862/20.10)")
