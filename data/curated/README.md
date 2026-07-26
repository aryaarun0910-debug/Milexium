# data/curated/ : real demand data and real-data models

Everything here is real, public, reproducible. No synthetic rows.

## Data ladder

1. NYC Access-A-Ride (data.ny.gov hasd-hdb7, vxuj-8kew): actual paratransit
   bookings from the largest US paratransit operation. Hourly by borough and
   provider type, Jan 2024 to May 2026, 26.3M trips. This is the product's
   exact target variable.
2. Chicago TNP (data.cityofchicago.org m6dm-c72p, n26f-ihde, 6dvr-xwnh):
   555.4M rideshare trips from Nov 2018 through May 2026, aggregated
   server-side to a 77-community-area hourly panel. Door-to-door demand at scale.
3. NYC TLC FHVHV parquet (CloudFront CDN): about 1.5B raw trips, roughly
   40 GB, monthly files. Transformer-scale corpus; aggregated locally with
   DuckDB, trained on Kaggle GPUs (see forge/legacy/kaggle/).

## Scripts

```
py -3 data/curated/fetch_nyc_aar.py         # AAR hourly + daily panels
py -3 data/curated/fetch_weather.py         # Open-Meteo daily, Chicago + NYC
py -3 data/curated/fetch_chicago_panel.py   # Chicago zone-hour panel (concurrent, day-chunked, resumable)
py -3 data/curated/fetch_mta_apc.py         # MTA bus + subway hourly ridership (real AFC/fare-payment data, resumable)
py -3 data/curated/fetch_tlc_parquet.py     # bulk FHVHV parquet (resumable)
py -3 data/curated/aggregate_tlc.py         # DuckDB: parquet -> zone-hour panel
py -3 data/curated/train_real_models.py     # models + conformal + metrics_real.json
py -3 data/curated/backtest_and_explain.py  # walk-forward backtest + SHAP explainability
py -3 data/curated/make_real_demo_assets.py # real-data "why this forecast" + demand curve PNGs
```

## Modeling protocol (same as the synthetic pipeline, deliberately)

Strict temporal split into four non-overlapping 90-day-or-longer blocks:
train, tune (XGBoost's eval_set for early stopping only), cal (split-conformal
calibration only, never seen during fit), valid (final reporting, never
touched by fit or calibration). Earlier versions of this pipeline reused the
calibration block for early stopping too, which forfeits the clean
split-conformal exchangeability guarantee; fixed 2026-07-21, see
forge/knowledge/docs/JOURNAL.md. XGBoost count:poisson with calendar, weather, and
demand-history features (lags available at day-ahead forecast time).
Always reported against a seasonal-naive baseline: mean of the same
(zone, hour, day-of-week) slot over the pre-validation window.
Split-conformal prediction intervals (Mondrian, binned by predicted decile,
90 percent target), coverage reported on the untouched validation window.

## Current results (data/curated/metrics_real.json)

NYC Access-A-Ride, borough-hour, 90-day holdout ending 2026-05-31 (clean
train/tune/cal/valid split):
- Model R2 0.985, MAE 20.4, RMSE 36.0
- Seasonal-naive R2 0.923, MAE 55.5, RMSE 82.5
- Conformal: 90 percent target, 97.8 percent achieved (conservative; the
  calibration window straddled winter)
- These numbers are materially unchanged from the pre-fix run (R2 0.987 vs
  0.985), which is reassuring: the original result was not an artifact of
  the tune/cal conflation, just not rigorously isolated from it.

Without the demand-history lags, the calendar-plus-weather model ties the
naive baseline (R2 0.919 vs 0.921). That finding is kept on purpose: it is
why every Milexium number ships with the naive comparison.

Chicago TNP, community-area-hour (77 zones), same 90-day holdout, 4.6M
training rows spanning 2018-11 to 2025-09:
- Model R2 0.966, MAE 15.8, RMSE 48.3
- Seasonal-naive R2 0.936, MAE 24.4, RMSE 65.8
- Conformal: 90 percent target, 92.6 percent achieved (tighter than AAR's,
  worth investigating why — larger zone count or different demand
  variance shape are both plausible, not yet checked)
- A second real city on the same recipe, same honest protocol: the model
  beats naive by a comparable margin to AAR, which is the actual claim
  ("this generalizes"), not either single number in isolation.

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

## Two data trees, and why they are not merged

`data/curated/` and `data/` are not duplicates.

- **`data/curated/`** — the original product: the real panels, the five trained
  models, `train_real_models.py`, `leakage_audit.py`, the model cards.
  Hand-acquired before the governed estate existed.
- **`data/`** — the governed estate (blueprint 17, ADR-0013): manifest-gated,
  rights **must** be declared, checksum-verified, content-addressed, MinIO-backed.

They are **deliberately not merged**. `data/curated/` paths are load-bearing: the
evidence registry pins those panels *and their sha256* (hashes that had to be
made cross-platform-stable via `.gitattributes` after CI caught a CRLF/LF
mismatch), the forecast/leakage/teardown suites read those exact paths, and nine
ADRs cite them. A move would break recorded provenance to buy tidiness.

What *was* closed is the real inconsistency: `data/curated/` held real TLC/MTA/
Chicago data with **no declared rights** while `data/` refuses a byte without
them. Both trees now sit under one governance model — see
`data/acquired/catalog/realdata-*.manifest.json`, generated by
`talos/tools/build_realdata_manifests.py` and held by
`aletheia/conformance/property-tests/test_realdata_governance.py` (ADR-0053). Those are
**governance-only** manifests: nothing was moved, and no `.acquired.json` is
written, because these datasets never went through `themis.estate.acquire` and
claiming otherwise would forge the provenance the estate exists to guarantee.
