# ADR-0016: Forecast runtime serving hash-verified registered models (Program E v0.1)

- **Status:** Accepted
- **Date:** 2026-07-23

## Context

This repository has real, trained, evaluated forecasting models
(`docs/MODEL_CARDS.md`), catalogued as `ModelVersion` entities by the model
registry (Program D, ADR-0010). But they were reachable only through ad-hoc
scripts in `realdata/`. The strategic direction (a runtime other software
integrates) needs the real forecasting *served through the runtime*, not left
as a pile of scripts — "the runtime serves a forecast," not "we have models."

## Decision

`packages/forecast/` (`ForecastRuntime`) is the join between the registry and
the real XGBoost artifacts:

1. Resolve the champion `ModelVersion` for a task from the `ModelRegistry`
   (`NoChampionError` if none promoted).
2. Load its booster from a filesystem path via an **injected**
   `artifact_resolver` (the runtime does not hardcode where artifacts live —
   works for `realdata/output/*_model.json`, a test's temp model, or a future
   object store).
3. **Hash-verify before trusting**: the loaded file's sha256 must match the
   registered `ModelVersion.artifact_hash`, else `ArtifactIntegrityError`. A
   stale, swapped, or corrupted model file is caught before it can produce a
   forecast — the same generator/verifier-separation discipline as
   `packages/verify`. Models with a non-hash placeholder
   (`NOT_COMPUTED:...`, e.g. the NTD model, ADR-0010) are refused, not
   silently served.
4. Predict on a point-in-time feature row (every schema feature must be
   present — a missing feature raises, never silently defaults to zero and
   produces a quietly-wrong number), bind features by the registered
   `feature_schema_version` (`packages/forecast/features.py` maps the two real
   schema labels to their exact ordered feature lists), and emit a canonical
   `ForecastVintage`.

Feature-schema label → feature-name binding lives in
`packages/forecast/features.py`, sourced exactly from
`realdata/train_real_models.py` (zone-hour, 16 features) and
`realdata/model_ntd_monthly.py` (agency-month).

## Consequences

- Status is **Demonstrated on real aggregate public data** — the runtime
  serves a genuine prediction from the actual committed Access-A-Ride booster
  (a conformance test proves it locally; it skips where the gitignored
  artifact is absent). It is not **Validated**: aggregate forecasts do not
  validate individual dispatch, and a `ForecastVintage` interval is a declared
  model interval, NOT a probability or guarantee (blueprint 01). The runtime
  records the numbers; it does not upgrade their status.
- `xgboost` and `pandas` are imported lazily inside the methods that need
  them, so importing the package for its types/errors doesn't require them.
- Not built (Specified): online/streaming inference, serve-time conformal
  recalibration, drift/change-point services, model routing beyond champion
  lookup. This is the batch point-in-time slice.
- Exposing forecasts through the `MilexiumClient` SDK is a clean follow-up
  (the SDK would gain a `forecast(...)` method delegating here) — deliberately
  not done in this packet to keep the just-committed SDK surface stable.
