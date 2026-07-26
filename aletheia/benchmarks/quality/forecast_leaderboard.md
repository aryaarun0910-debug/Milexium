# Forecast demand leaderboard -- honest results
_Generated 2026-07-26T14:12:13.318860+00:00 by `aletheia/benchmarks/quality/build_forecast_leaderboard.py`. Every value is copied verbatim from a committed metrics file and carries its source file + JSON-path in `forecast_leaderboard.json`._

Real demand forecasts on real AGGREGATE public data under strict temporal (forward) evaluation. Demonstrated, NOT operator-validated dispatch. A metric is not a probability. Every model is shown against its own seasonal-naive baseline.

## How to read this
- **Protocol.** Strict temporal holdout: four non-overlapping >=90-day blocks (train/tune/cal/valid); the validation window is never touched by fit or calibration. Metrics reported on that untouched window.
- **Baseline.** seasonal-naive = mean of the same (zone, hour, day-of-week) slot over the pre-validation window (monthly NTD uses the analogous seasonal-naive). Every model is shown against it -- no model is shown alone.
- **Not a cross-model ranking.** This is NOT a ranking of models against each other: R2/MAE are not comparable across different spatial/temporal grains and different series. Each row is scored only against ITS OWN seasonal-naive baseline. Rows are ordered product-target first, then generalization models, then the national monthly model.
- **Honest limits.** Demonstrated on real *aggregate* public data, not operator-validated trip-level dispatch. A metric is not a probability. External validity to a specific operator's own bookings is unproven until a pilot.

## Leaderboard
Headline metric is R2 (higher is better), shown model vs its seasonal-naive baseline; the MAE column shows the error reduction over that same baseline.

| model | role | grain | eval window | R2 (model / naive) | beats naive? | MAE (model / naive) | MAE error reduction | source |
|---|---|---|---|---|---|---|---|---|
| NYC Access-A-Ride paratransit bookings (borough-hour) | PRODUCT TARGET | borough / hourly, day-ahead | 2026-03-02 to 2026-05-31 | 0.9857 / 0.9231 | yes | 20.12 / 55.49 | 63.7% | `data/curated/metrics_real.json` |
| Chicago TNP door-to-door trips (community-area-hour) | generalization evidence | community area (77 zones) / hourly, day-ahead | 2026-03-02 to 2026-05-31 | 0.9655 / 0.9362 | yes | 15.83 / 24.44 | 35.2% | `data/curated/metrics_real.json` |
| MTA bus AFC fare-payment ridership (route-hour) | generalization evidence | route / hourly, day-ahead | 2026-04-15 to 2026-07-14 | 0.9492 / 0.8262 | yes | 14.99 / 29.91 | 49.9% | `data/curated/metrics_real.json` |
| MTA subway AFC fare-payment ridership (station-hour) | generalization evidence | station / hourly, day-ahead | 2026-04-09 to 2026-07-08 | 0.9490 / 0.8602 | yes | 42.93 / 105.83 | 59.4% | `data/curated/metrics_real.json` |
| NTD national monthly demand -- cold-start (127 held-out agencies, no agency identity) | national onboarding evidence | agency (national, 637 agencies) / monthly | held-out 127 agencies (20%), no agency identity | 0.9757 / 0.9666 | yes | 1504.50 / 1734.20 | 13.2% | `data/curated/metrics_ntd_monthly.json` |
| NTD national monthly demand -- temporal (last 12 months, all agencies) | national market evidence | agency (national, 637 agencies) / monthly | temporal last 12mo, all agencies, full features | 0.8854 / 0.9715 | **NO** | 2704.90 / 1939.70 | **-39.4% (worse)** | `data/curated/metrics_ntd_monthly.json` |

## Where the model does NOT clearly beat naive (reported on purpose)
The repo's discipline is that every number ships with its naive comparison, including the unflattering ones:

- **without demand-history lags, the calendar+weather model ties the seasonal-naive baseline** -- R2 0.919 (model) vs 0.921 (naive) -- the lags, not the weather, are what beats naive (source: `data/curated/README.md`).
- **weather features barely move the AAR model (the lags carry it)** -- with-weather R2 0.9857 vs no-weather R2 0.9851, both far above the naive 0.9419 on this window (source: `data/curated/metrics_weather_ablation.json`).
- **NTD temporal split LOSES to naive on absolute R2** -- model R2 0.8854 vs naive 0.9715 (monthly demand is very stable YoY); the model wins on MAPE and on the cold-start split instead (source: `data/curated/metrics_ntd_monthly.json`).

## Not shipped (excluded from the leaderboard)
- **kaggle pretrain-then-finetune transformer** -- MODEL_CARDS.md 'Not shipped': run on real GPUs but LOST to XGBoost on AAR (R2 0.933 vs 0.986). R&D evidence, not a production model; we ship the simpler model on purpose. (source: `forge/legacy/kaggle/results/finetune_metrics_testmode.json`).

Mirrors MODEL_CARDS.md's own 'Not shipped' framing: the transformer is R&D evidence, not a production row, so it does not appear above.

## Reproduce / verify
```
py -3 aletheia/benchmarks/quality/build_forecast_leaderboard.py
py -3 -m pytest aletheia/conformance/property-tests/test_forecast_leaderboard.py -v
```
The conformance test re-reads each cited source JSON at the cited JSON-path and asserts every leaderboard cell matches -- so no value here is a hand-copied number.
