# ADR-0023: Golden-path end-to-end demo on real public data (Phase 2 proof)

- **Status:** Accepted
- **Date:** 2026-07-24

## Context

Pre-traction, the highest-leverage proof is a reproducible end-to-end run a
skeptic can execute and verify without a pilot (IMPLEMENTATION_STATUS "Phase 2
— undeniable public evidence", item 1). It must run on real public data, not
the fictional reference agency, and make its own real-vs-synthetic boundaries
visible rather than hiding them.

## Decision

`demo/golden_path.py` (`py -3 -m demo.golden_path`, plus a callable
`run_golden_path()` returning a structured result) drives the whole loop and
prints each step:

1. **Ingest** — 8 real NYC TLC FHVHV trips (`realdata/raw_tlc/`) via the
   shipped `TlcTripsAdapter` → `ServiceRequest`s. TLC was chosen over the
   acquired GTFS-Flex example because that feed carries only 2 service-*template*
   rows (bookable availability, not observed demand) — too thin for a decision
   problem — whereas TLC is millions of real individual trips in the same city
   as the AAR forecast model. Read via DuckDB (the env has neither pyarrow nor
   fastparquet; DuckDB reads the parquet lazily without loading 0.5 GB).
2. **Forecast** — a real ~55.5-booking next-hour prediction served from the
   real committed Access-A-Ride booster (`realdata/output/aar_model.json`,
   sha256-verified before predicting).
3. **Decide/override** — recommendation + human override recorded on the
   hash-chained ledger; solver returns a feasible plan the independent checker
   passes.
4. **Evidence** — an `EvidencePack` built and independently re-verified
   (in-process and from disk).
5. **Replay** — a baseline-vs-Milexium comparison, labelled a modelled
   comparison (not causal).
6. **Manifest** — a machine-readable `run_manifest.json` recording what was
   real, what was synthetic, and artifact hashes.

## What is real vs synthetic (made visible in the demo's own output)

- **Real:** the ingested demand (real TLC request times, O/D zones,
  wheelchair-request signal, with honest semantic-loss notes) and the forecast
  (real hash-verified booster).
- **Synthetic (labelled):** the fleet (no public fleet data exists), and the
  scheduling assumptions that turn a trip record into a schedulable request
  (pickup window, ride time, ADA ceiling; `must_serve=False` since FHVHV are
  ride-hail, not ADA-mandated).
- **Modelled:** the replay (both schedules are simulated counterfactuals).

The demo does not cherry-pick: served +2 and denials −2 favour Milexium while
**utilization favours the baseline** (one packed van is more utilized — the
service-level/utilization tradeoff), shown rather than hidden.

## Consequences

- Everything is **Demonstrated** — real public demand + real forecasts, but a
  synthetic fleet and a modelled replay; nothing is operator-Validated.
- Generated outputs (`evidence/artifacts/golden-path/*.json`) carry fresh UUIDs/
  timestamps each run and are gitignored; the demo code is the committed
  artifact and regenerates them on demand.
- Flagged (owned by `app/decide`): the v0.1 fixed-ride-time objective ties
  all all-served plans, so the exact solver needs a coarse 30-min grid + raised
  node budget to *certify* OPTIMAL rather than honestly TIMEOUT — a property of
  the solver, addressed further by the v0.2 DARP work (ADR-0024).
- A future stronger demo would use a consented operator's real fleet — the one
  thing that would move this from Demonstrated toward Validated.
