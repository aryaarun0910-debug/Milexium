# realdata/ : real demand data and real-data models

Everything here is real, public, reproducible. No synthetic rows.

## Data ladder

1. NYC Access-A-Ride (data.ny.gov hasd-hdb7, vxuj-8kew): actual paratransit
   bookings from the largest US paratransit operation. Hourly by borough and
   provider type, Jan 2024 to May 2026, 26.3M trips. This is the product's
   exact target variable.
2. Chicago TNP (data.cityofchicago.org m6dm-c72p, n26f-ihde, 6dvr-xwnh):
   every rideshare trip since Nov 2018, about 300M, aggregated server-side
   to a 77-community-area hourly panel. Door-to-door demand at scale.
3. NYC TLC FHVHV parquet (CloudFront CDN): about 1.5B raw trips, roughly
   40 GB, monthly files. Transformer-scale corpus; aggregated locally with
   DuckDB, trained on Kaggle GPUs (see kaggle/).

## Scripts

```
py -3 realdata/fetch_nyc_aar.py         # AAR hourly + daily panels
py -3 realdata/fetch_weather.py         # Open-Meteo daily, Chicago + NYC
py -3 realdata/fetch_chicago_panel.py   # Chicago zone-hour panel (concurrent, day-chunked, resumable)
py -3 realdata/fetch_mta_apc.py         # MTA bus + subway hourly ridership (real APC/AFC data, resumable)
py -3 realdata/fetch_tlc_parquet.py     # bulk FHVHV parquet (resumable)
py -3 realdata/aggregate_tlc.py         # DuckDB: parquet -> zone-hour panel
py -3 realdata/train_real_models.py     # models + conformal + metrics_real.json
py -3 realdata/backtest_and_explain.py  # walk-forward backtest + SHAP explainability
```

## Modeling protocol (same as the synthetic pipeline, deliberately)

Strict temporal split: last 90 days validation, prior 90 days calibration,
rest training. XGBoost count:poisson with calendar, weather, and
demand-history features (lags available at day-ahead forecast time).
Always reported against a seasonal-naive baseline: mean of the same
(zone, hour, day-of-week) slot over the pre-validation window.
Split-conformal prediction intervals (Mondrian, binned by predicted decile,
90 percent target), coverage reported on the untouched validation window.

## Current results (realdata/metrics_real.json)

NYC Access-A-Ride, borough-hour, 90-day holdout ending 2026-05-31:
- Model R2 0.987, MAE 19.7, RMSE 34.3
- Seasonal-naive R2 0.923, MAE 55.5, RMSE 82.5
- Conformal: 90 percent target, 98.1 percent achieved (conservative; the
  calibration window straddled winter)

Without the demand-history lags, the calendar-plus-weather model ties the
naive baseline (R2 0.919 vs 0.921). That finding is kept on purpose: it is
why every TransitPulse number ships with the naive comparison.

Walk-forward backtest (4 rolling 90-day folds, expanding training window,
see backtest_and_explain.py): model R2 0.972 mean (std 0.023) vs naive
0.919 mean (std 0.025) — consistent across folds including a harder winter
fold, not a single lucky holdout window. SHAP explainability on the
production model: lag7 (same day last week) dominates global feature
importance; worked "why this forecast" examples in explanations_aar.json.

raw_tlc/, output/, and the large aggregated panels (MTA bus/subway,
Chicago, and their per-month checkpoint directories) are gitignored —
regenerate via the fetch scripts above. Only the compact panels (AAR,
weather) are committed as the reproducible evidence trail.
