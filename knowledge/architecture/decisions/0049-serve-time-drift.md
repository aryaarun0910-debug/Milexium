# ADR-0049: Serve-time drift monitoring — the runtime now withdraws a guarantee it cannot support

- **Status:** Accepted
- **Date:** 2026-07-25
- **Packet:** MX-E-SERVE-TIME-DRIFT-007

## Context

ADR-0034 built a drift service (PSI, two-sample KS, CUSUM). ADR-0030 built
serve-time conformal intervals. **They were never connected.** A model could
drift arbitrarily far from its training distribution and the runtime would keep
serving confident forecasts with valid-*looking* intervals — silently wrong,
with an interval asserting it was fine. For a design partner that is the worst
failure mode available.

ADR-0030 had already measured the shift: committed AAR intervals **overcover
(98.1% against a 90% target)**, isolated to a winter→spring distribution shift,
with a random exchangeable split recovering ~90%. The evidence existed; the
runtime just could not say it.

## Decision

`app/forecast/serve_drift.py` plus an **additive**
`ForecastRuntime.forecast_monitored` (the existing `forecast` path is untouched).
`app/core/drift.py` is imported **read-only** — verified: there is no second
PSI/KS implementation.

**The interval-validity caveat is the point of the packet.** A split-conformal
interval is distribution-free *only under exchangeability*, and detected input
drift is direct evidence against that assumption. So `MonitoredForecast` carries
the vintage and the verdict in **one object**, exposing `drift_status`,
`interval_guarantee` (`unqualified` / `unsupported` / `not_assessed`),
`interval_guarantee_supported` and `interval_caveat`. `summary()` renders the
number and the caveat on one line — **they are not separable**, so a caller
cannot quote the estimate without the qualification travelling with it.

**Report, do not decide.** Deciding what to do about drift — retrain, roll back,
refuse — belongs to the promotion controller and the operator, exactly as
ADR-0034 established when it kept detection separate from action. A monitor that
silently changes what serves is worse than one that warns. This is **asserted,
not documented**: a parametrised test compares `MonitoredForecast.vintage`
field-by-field against what the unmonitored `forecast()` returns — same point,
same bounds, same model id. No widening, no clamping, no suppression.

## Consequences

**23 new tests, none skipped.** Demonstrated on the real committed AAR booster
(hash-verified through the runtime) with the reference derived from the model's
**own training window** (`date <= 2025-09-03`, the `train_span` in
`metrics_real.json`), rebuilt with `train_real_models.py`'s exact recipe.

Serving the untouched spring-2026 validation window — **the exact window
ADR-0030 measured at 98.1% coverage** — **8 of 15 monitored features drift**
(`month` PSI 9.00; `tmin_c` 0.63; `tmax_c` 0.43; `roll28` 0.115 moderate; plus
corrected-KS rejections on the lags and precipitation).

**The control is what makes it real:** a random *exchangeable* split of the same
training window reports `no_drift`, zero features flagged — the same control
ADR-0030 used to isolate winter→spring as the cause. So ADR-0030's overcoverage
stops being a curiosity and becomes a **predicted consequence the runtime can
now state at serve time**.

Three design calls worth recording:

- **The artifact carries no reference, and the code says so rather than
  inventing one.** `ModelVersion` has `training_data_manifest_hash` and an eval
  window but no per-feature distribution, so `reference_from_model_artifact()`
  returns `None` **with a recorded reason**. The fallback derivation is pinned in
  a `ReferenceProvenance` carrying the panel SHA-256 (asserted against the file
  on disk), window, row counts, subsample seed, recipe, and every skipped feature.
- **`insufficient_data` is a third status, never folded into `no_drift`** — and
  it sets `interval_guarantee_supported = False`, because **untested is not
  supported**.
- **KS is Bonferroni-corrected across features.** Uncorrected, 15 features at
  α=0.05 would flag a healthy serve roughly half the time; a 30-serve batch test
  pins the false-drift rate.

**Honest limitations:**

- **Covariate drift only.** Concept drift (X→y changing while inputs hold) is not
  detected — that needs actuals and belongs to the promotion controller's gate.
- **Continuous features only.** The categorical zone column is skipped with a
  recorded reason; no chi-square test is wired.
- **CUSUM deliberately not wired in** — it monitors a stream over time, a
  different surface from a point-in-time serving batch.
- **The monitor withdraws the guarantee; it does not repair it.** Weighted or
  adaptive conformal under drift is not built. Honest, not useful.
- `MIN_ROWS_FOR_STABLE_STATISTIC = 30` and the PSI bands are rules of thumb, not
  operator-calibrated.

Status: **Demonstrated**.
