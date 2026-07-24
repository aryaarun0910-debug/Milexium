# ADR-0030: Serve-time conformal uncertainty + all real models in the runtime (Program E depth)

- **Status:** Accepted
- **Date:** 2026-07-24

## Context

Phase 3 item E deepens the forecast runtime (ADR-0016): the runtime served a
point estimate with only a manual `interval_half_width`, and demonstrated
serving only the Access-A-Ride model. Two real deepenings raise the credibility
of the forecasting evidence: real serve-time prediction intervals, and serving
every real model this repo has.

## Decision

**Serve-time conformal uncertainty** (`packages/forecast/conformal.py`):
`ConformalCalibration` — a frozen value object holding signed additive offsets
(`lower_offset`/`upper_offset`), `target_coverage`, `n_calibration`, and a
`clip_nonnegative` flag mirroring the pipeline's `np.clip(pred, 0, None)`.
Fitters: `fit_symmetric_conformal` (split-conformal on `|residual|`),
`fit_two_sided_conformal` (independent tail quantiles for skew),
`fit_conformal_from_predictions`, and `empirical_coverage`. The order-statistic
index is `ceil((n+1)·coverage)` — numerically identical to
`realdata/train_real_models.py`'s conformal, so a fit here reproduces the
committed model-card half-widths.

- **Global (unconditioned) split-conformal**, not the repo's Mondrian
  hour-bucket variant — justified by the repo's own null result
  (`docs/RND_QUESTIONS.md` Q4: hour-bucket conditioning gave no improvement,
  97.8% vs 98.1%). Symmetric by default (matches the pipeline); two-sided
  available for skew.
- `ForecastRuntime.forecast(...)` gains an optional `calibration`; supplying it
  emits real `interval_low`/`interval_high`. The manual `interval_half_width`
  path is untouched; supplying both raises (mutually exclusive).

**All real models served** (`packages/forecast/features.py`): each booster's
`.feature_names` was read — the four zone-hour models share 15 calendar/weather/
lag features but the **trailing zone column differs**, so each gets its own
schema (`zone_hour_demand_v1`=borough/AAR, `_area_v1`=Chicago, `_route_v1`=MTA
bus, `_station_v1`=MTA subway). All four now serve a plausible hash-verified
forecast through the runtime.

## The honest coverage finding (measured, on committed validation artifacts)

Target 90%, reproduced from `realdata/output/*_valid.csv.gz`:

| Model | Committed intervals (winter-cal → spring-valid) | Exchangeable random split |
|---|---|---|
| AAR | **98.1%** (strong overcoverage) | 89.5% |
| Chicago | 92.6% | 89.9% |
| MTA bus | 92.0% | 90.0% |
| MTA subway | 91.7% | 90.0% |

The committed intervals overcover; refitting conformal on a random *exchangeable*
split of the same window recovers ~90%. This **isolates the overcoverage cause
as the winter-calibration → spring-validation distribution shift, not the
method** — empirically confirming the `RND_QUESTIONS.md` Q4 hypothesis. Tests
assert both directions.

## Consequences

- A conformal interval is distribution-free only **under exchangeability** — a
  marginal coverage property, NOT a per-forecast probability or guarantee — and
  loses its guarantee under drift, which is exactly what the AAR 98.1%
  overcoverage demonstrates. Documented and asserted.
- Status stays **Demonstrated** on real aggregate data — not operator-Validated.
- 28 tests. Not built (Specified): serve-time recalibration under detected
  drift, drift/change-point services, model routing beyond champion lookup.
- The overcoverage finding is itself a defensibility signal: the system measures
  and reports where its own intervals are miscalibrated rather than asserting
  nominal coverage.
