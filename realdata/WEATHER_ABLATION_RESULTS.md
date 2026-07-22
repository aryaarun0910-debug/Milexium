# Weather feature ablation: does weather actually help?

`weather_ablation.py`. Metrics: `metrics_weather_ablation.json`. AAR, 90-day
holdout ending 2025-08-20 (inside the hourly-weather coverage window), weather
feature set ablated, everything else identical.

| Feature set | R2 | MAE |
|---|---|---|
| none (calendar + lags only) | 0.9851 | 18.59 |
| + daily weather (production) | 0.9853 | 18.82 |
| + hourly weather (NOAA NCEI) | 0.9849 | 18.57 |
| + daily AND hourly | 0.9857 | 18.73 |

(naive baseline R2 0.942 on this window)

## Finding: weather adds essentially nothing, and we say so

All four feature sets land within noise (R2 0.985-0.986, MAE 18.6-18.8).
Neither daily nor hourly weather meaningfully improves the AAR forecast. This
confirms, with a number, what the SHAP analysis implied: demand-history lags
carry ~80% of the signal, and paratransit demand is driven far more by
standing-order structure (dialysis MWF, day programs) and recent history than
by weather.

## What we do with it (honest, not wasteful)

- **Keep the daily weather feature** (production default): it costs nothing,
  is trivially available at forecast time, and does no harm.
- **Do NOT add hourly weather as a feature.** We downloaded and committed the
  NOAA hourly panel; the honest conclusion is it does not earn a place in the
  paratransit demand model. It remains available for other uses (fixed-route
  phase 2, where intra-day weather may matter more), but it is not wired into
  the shipping model, because the evidence says it would be complexity without
  benefit. Testing before adding is the discipline; this is the payoff.

Coverage note: the hourly panel ends 2025-08-25 (NOAA NCEI publication lag),
so this ablation validates on a mid-2025 window it covers, not the production
2026 window. Stated plainly; it does not change the conclusion (weather is
marginal in every window tested).
