# ADR-0057: What each adapter actually carries — and the identifier that is a person

- **Status:** Accepted
- **Date:** 2026-07-25
- **Packet:** MX-B-ADAPTER-REFS-009
- **Closes:** the limitation ADR-0054 recorded against itself

## Context

ADR-0054 closed the run-reference chain for `operator_export.py` and named its own
gap: *"the other adapters (TIDES, GTFS-Flex, TLC, GTFS-Realtime) are unchanged;
where they carry a vehicle reference it is still unwired."*

Deadhead is measurable only by chaining one vehicle's consecutive trips
(ADR-0039), so this is the field the entire teardown depends on.

## Decision

Establish, per adapter, **what the source format actually carries** — and where it
carries nothing, record that rather than synthesise it.

| Adapter | Vehicle | Run | Outcome |
|---|---|---|---|
| **TIDES** | `vehicle_id` | `block_id` | Both wired; chain proven end-to-end |
| **GTFS-Realtime** | `vehicle.id` | **none** | Vehicle wired; absence recorded per row |
| **TLC FHVHV** | **none** | **none** | Nothing to wire; refusal gate added |
| **GTFS-Flex** | **none** | `block_id` (optional) | Absence *measured* per row |

**TIDES** is the only source carrying both. `block_id` is a day's chained vehicle
work — the same concept `Block.block_ref` documents. The chain is proven on
**both** canonical engines: TIDES row → `Outcome` → MilexiumDB → read back →
`VehicleSegment` → `teardown_deadhead`, with every figure re-derived from what
came *out of* the store rather than what went in.

**GTFS-Realtime carries no run, and `trip_id` is not a substitute.** Keying runs
on `trip_id` reports every vehicle's day as single-trip runs with no gaps between
them — i.e. **zero deadhead**. The field that would serve lives in *static* GTFS
`trips.txt`, not in the realtime TripDescriptor. Recorded as
`NO_RUN_REFERENCE_FIELD` on every row.

**TLC FHVHV carries neither, verified rather than assumed** — by reading the
parquet footers of the real 2019-02 (24 columns) and 2026-05 (25) files. No hack
licence, medallion, plate, VIN, driver id or vehicle id. `hvfhs_license_num` is
the *company* licence (four distinct values across 20M rows). The consequence is
stated plainly: **no deadhead is measurable from this source at all.**

### The identifier that is a person

The packet was briefed to reason about whether a TLC hack/licence number could
serve as a vehicle reference. The answer is no, and the reasoning is the durable
part:

1. **It isn't a vehicle.** A hack licence is a *driver's* licence — a person. The
   repo's existing analogue is `RunPiece.operator_ref`, already documented as a
   person reference.
2. **It is directly identifying.** TLC publishes a licensee lookup. Not
   hypothetical for this dataset: the 2013 release hashed medallion and hack
   licence with MD5 and was de-anonymised within days, because the input space is
   enumerable.
3. **The subtle half, and the one worth keeping:** in an owner-operator fleet —
   most of the FHV trade — vehicle and driver are 1:1, so **even a genuine
   vehicle id is a pseudonymous person id.** `vehicle_ref` is safe for an
   agency's numbered bus and not for a single-vehicle licensee. **The question is
   fleet shape, not column name.**
4. **Where the gate must live.** `Outcome.vehicle_ref` has no tokenisation, and
   `VehicleSegment._reject_rider_identifier` inspects the *column name* a caller
   points at — so it would wave through a person id already laundered into the
   canonical field. The refusal therefore sits at the adapter, **ahead of the
   required-column check**, and the ordering is tested as behaviour.

A live defect was closed on the way: such a column previously became an
`unmapped_extension` with `source_value=str(value)`, **echoing the raw identifier
into the loss report**.

## Consequences

**49 new tests, 0 skipped**, both canonical engines plus the PostGIS observation
store — no leg skipped. Connect surface **426 → 475 passed**; no existing test
edited or removed.

**23 mutation checks, 23 RED**, including: back-fill block from vehicle; stop
writing `run_ref`; *delete* the narrowed loss record (the easy move ADR-0054
warns against); default `served=True`; back-fill the RT vehicle from
label/plate/`trip_id`/entity id; run the TLC gate after the required-column
check; keep the raw identifier in the quarantine.

One mutation came back **green — and the mutation was wrong, not the test.** It
rewrote a line the test does not assert on; reverting the reason whole is RED.
Recorded because **a mutation that fails to mutate is exactly how a vacuous test
gets certified sound** — and this repo has found four vacuous tests this month.

### Honest limitations

- **Two entry points for one TIDES row.** `parse()` was not changed to return the
  composite, so a caller reaching for the obvious method name gets output with no
  reference in it. Bounded by construction and pinned by a mutation-checked test,
  but it is a deviation from ADR-0054's pattern, forced by the owned-path
  boundary.
- **The GTFS-RT durable leg has a seam.** `observations_within` is the only read
  returning a vehicle ref and it does not return `observed_at`. Persistence and
  teardown are joined by an assertion, not by one data path — **strictly weaker
  than the TIDES chain**, and it should not be described as equivalent.
- **`classify_pii_column` does not catch `hack_license`, `medallion`,
  `license_plate` or `vin`** (ADR-0051's `driverlicen` substring catches only
  `driver_license`). The vocabulary was added *locally* to `tlc_trips.py` rather
  than widening the shared classifier, because widening it changes what
  `operator_export.py` quarantines for reasons unrelated to taxis. **Whether the
  shared classifier should learn these terms is open.**
- **Only 2 of 5 adapters have a PII gate at all.** TIDES, GTFS-Flex, GTFS-RT and
  reference-agency have none, so "the gate still runs first" is literally
  testable on two. TIDES `operator_id` is person-adjacent and currently flows into
  a loss record with its raw value.
- **The TLC gate is name-based and untested against real drift** — it would miss
  `driver_ref` or `operator_hack`.
- **GTFS-Flex's absence is measured on a one-trip feed.** "Empty throughout the
  acquired feed" is a statement about a single `trips.txt` row.
- **TIDES teardown minutes are a mapping gap, not a source gap** — TIDES publishes
  `actual_trip_end` and it simply is not mapped.
- **TIDES `served` vocabulary is exactly `{canceled, cancelled}`.** An export
  writing `CANCELLED_NO_SHOW` lands in the quarantine branch — safe direction, but
  it imports zero performed trips without naming the vocabulary as the cause.
- **Second consecutive packet blocked by the same fixture.** An adapter
  conformance test outside the owned paths pins
  `lost['vehicle_id'].disposition == 'dropped'` — the exact record a correct
  wiring must move — so every change had to be additive. This should be fixed
  centrally rather than worked around a third time.

Status stays **Demonstrated** for all four. Every fixture is synthetic or public
open data.
