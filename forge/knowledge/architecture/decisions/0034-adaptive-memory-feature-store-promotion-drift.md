# ADR-0034: Adaptive-memory v0.1 — point-in-time feature store, promotion lifecycle, drift detection

- **Status:** Accepted
- **Date:** 2026-07-24
- **Packet:** MX-D-ADAPTIVE-MEMORY-002 (Phase-3 gate item D)

## Context

Program D (Core / adaptive memory) had only a v0.1 model+task registry
(ADR-0010): a single champion pointer per task that `promote()` overwrites
without evaluation, and no feature store or drift monitoring. Phase 3's D gate
asks for a real slice of the adaptive-memory substrate
(`blueprint/05-core-model-runtime-and-forecast.md`): a leakage-safe
point-in-time feature store, a champion/challenger/canary lifecycle beyond the
single pointer, and drift/change-point detection — Demonstrated on real or
public data, honoring `data/curated/leakage_audit.py`'s point-in-time discipline.

## Decision

Three additive in-memory reference modules under `themis/core/` (mirroring the
`ModelRegistry` / `HashChainAppender` reference-backend pattern), each with
conformance tests. Nothing existing was edited; the registry is imported
read-only.

**`feature_store.py` — leakage-safe point-in-time store.** The load-bearing
invariant: `get_features(entity_id, as_of=t)` returns, per feature, the latest
value whose `knowledge_time` is **strictly `< t`**. A value stamped exactly at
`t` or later is never visible — that strict `<` *is* the leakage guarantee, so a
feature built from this store cannot secretly depend on the future. Append-only
(a correction is a new value at a later/equal knowledge time; ties resolve to
the last write). Entity ids are opaque strings only (no PII; trusts upstream
tokenization, as `ServiceRequest.rider_ref` does).

**`promotion.py` — champion/challenger/canary `PromotionController`.** COMPOSES
`ModelRegistry` read-only (never calls `register()`/`promote()`), owning the
richer role state itself. A challenger becomes champion **only** through
`evaluate_and_maybe_promote`, which records a `PromotionDecision` (metric
comparison + margin + verdict + rationale) — the promotion analogue of the
ledger's "why not the alternatives". A canary carries a traffic fraction in
`[0, 1)` and `route(roll)` is deterministic given the caller's RNG draw.
Rollback demotes to the prior champion off a history stack and is recorded; the
demoted champion rejoins the challenger pool.

**`drift.py` — detection service (pure numpy, no scipy/sklearn).** Distribution
drift via `population_stability_index` (quantile bins, ±inf tails, epsilon floor)
and `ks_two_sample` (max-CDF-gap statistic + the Stephens-corrected asymptotic
Kolmogorov survival p-value); change-point via `cusum_change_point` (two-sided
tabular CUSUM standardized by a reference window, reporting first crossing index
+ direction). Detection ONLY — acting on a flag (retrain, roll back) is the
promotion controller's / operator's job, kept separate so a monitor cannot
silently change what serves.

## Consequences

- **52 conformance tests** (feature_store 13, promotion 22, drift 17), all
  green in isolation; `py -3 -m pytest themis/core-tests` equivalents pass.
- **The leakage guarantee is proved mechanically on REAL data.** A
  future-corruption test on `data/curated/panels/aar_daily.csv` (NYC Access-A-Ride
  daily, labelled `REAL DATA`) corrupts every row after a cutoff, rebuilds the
  store, and asserts every as-of read at a label time ≤ cutoff is bit-identical
  — at three cutoffs across the timeline — mirroring `data/curated/leakage_audit.py`,
  with a control proving a post-cutoff read *does* change.
- **Drift demonstrated on a real regime shift:** the March-2020 COVID collapse
  in the AAR panel is detected as a downward CUSUM change-point; PSI+KS flag
  pre-crash vs. the April trough; a random exchangeable split of stable-year
  2023 correctly does *not* flag.
- **Honest v0.1 limits:** all three are in-memory reference backends (no
  persistence/concurrency); feature values are `float` only; the
  `PromotionController` deliberately does **not** sync the registry's ADR-0010
  single-pointer champion (the two mechanisms coexist rather than being
  unified — a later reconciliation); CUSUM has a bounded (non-zero) false-alarm
  rate and KS uses the asymptotic (not exact small-sample) p-value — both stated
  honestly rather than papered over. Status is **Demonstrated** (synthetic
  streams + one real aggregate panel), never operator-Validated.
