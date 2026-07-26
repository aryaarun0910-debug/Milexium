# ADR-0019: Historical replay + baseline-vs-Milexium comparison (Program H v0.1)

- **Status:** Accepted
- **Date:** 2026-07-24

## Context

Phase 1 needs the "prove the decision improved the outcome" surface — replay a
day against a baseline and compare operational metrics. Two hard boundaries from
`blueprint/01`: "Replay is a modelled comparison, not causal proof of savings"
and "Public aggregate data validates aggregate demand tasks, not individual
dispatch." Plus the first technical failure mode in `blueprint/15`: future data
must not leak into replay.

## Decision

`aletheia/replay/`:

1. **Information-cutoff replay** (`replay.py`): reconstructs "what was known as
   of instant T" by delegating to the canonical `RequestTimes.known_as_of` —
   the **sole** cutoff authority, so the no-future-leak rule cannot diverge from
   the canonical one. "Future leak" is *defined as* "what `known_as_of` would
   mask." `verify_no_future_leak` rejects an as-of state still carrying a
   post-T fact.
2. **Baseline-vs-Milexium comparison** (`comparison.py`): `compare_schedules`
   requires both `ScheduleOutcomeSet`s to cover the identical request-id set,
   and computes six roadmap metrics (served trips, denials, on-time pickup rate,
   mean excess ride time, total deadhead, utilization) from one `METRIC_SPECS`
   source of truth, each as a `MetricDelta` (baseline, Milexium, delta,
   `higher_is_better`, `favors_milexium`). Unknowns are `None`, never guessed.
3. **`ReplayManifest`**: pins the request-set identity (order-independent
   `request_set_sha256`), replay instant, both outcome sources + provenance, the
   exact metric definitions, and a deterministic `replay_id` — reproducible and
   auditable, mirroring the evidence-pack manifest.

The "modelled comparison, not causal proof" boundary is enforced **three ways in
code**, not just prose: a single-sourced `MODELLED_COMPARISON_NOTE`; a
`field_validator` that *raises* if `causal_proof` is set `True`; and structural
`provenance` (observed|simulated) / `basis` (recorded_outcomes|
modelled_fleet_accounting) fields. No monetary/savings field exists anywhere (a
test enforces it).

## Consequences

- Everything is **Demonstrated** on synthetic data — no operator data, no dollar
  claims, no causal claims. A baseline counterfactual is always a modelled
  comparison.
- Utilization is the one metric sourced from optional modelled fleet accounting
  (`available_/productive_vehicle_minutes` on the outcome set), reported `None`
  when absent — the seam to revisit once a real scheduler (Program F) emits
  per-vehicle utilization.
- A self-comparison yields all-zero deltas (metamorphic test) — a sanity anchor.
- Not built (Specified): discrete-event simulation, disruption worlds, latent
  world models, causal/uplift evaluation with identification assumptions.
