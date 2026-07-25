# ADR-0054: Closing the run-reference chain, adapter to teardown

- **Status:** Accepted
- **Date:** 2026-07-25
- **Packet:** MX-B-RUNREF-WIRING-008

## Context

Three ADRs had each done their part of this and left a seam between them.

ADR-0038 surfaced that `vehicle_ref`/`run_ref` had no canonical home, so
`operator_export.py` recorded them as a `dropped` semantic loss on **every row**.
ADR-0043 gave them a home — two nullable columns on `outcomes`, with
`record_outcome()`/`outcomes()` on both stores. But the adapter was outside that
packet's owned paths, so it kept reporting the field as lost **even though it now
persisted**.

The consequence was not cosmetic. Deadhead is measurable only by chaining one
vehicle's consecutive trips (ADR-0039), so the single field the entire teardown
depends on was being reported to the operator as discarded, and the handoff
adapter → `Outcome` → store → teardown was demonstrated nowhere.

## Decision

Carry the reference through to the canonical `Outcome`, and narrow the
semantic-loss record to what is *actually* still lost rather than deleting it.

**The wiring is trivial. The proof that the chain closes is the deliverable.**

## Consequences

**151 tests pass** across the wiring, the original operator-export suite and the
messy-data suite. The tests worth naming are the ones that constrain what the
wiring must *not* do:

- **`test_a_missing_run_reference_is_never_backfilled_from_the_vehicle_number`**
  — an export naming no run must not have one inferred from an adjacent field.
  ADR-0039 made `unattributable` a first-class output precisely so missing
  attribution stays visible; quietly filling it would corrupt every denominator
  downstream while looking tidier.
- **`test_the_trips_whose_export_named_no_run_stay_unattributable`** and
  **`test_an_export_naming_no_run_at_all_produces_a_wholly_unattributable_teardown`**
  — the absence survives the whole chain, not just the adapter.
- **`test_the_run_reference_survives_the_whole_chain_into_a_teardown`** — the
  end-to-end path that was impossible before this packet.
- **`test_the_reference_is_no_longer_reported_as_lost`** paired with
  **`test_what_legitimately_remains_lost_is_recorded_and_is_narrower`** — the
  loss record was narrowed, not deleted. Deleting it would have been the easy
  move and would have silently dropped a genuine residual claim.
- **`test_the_chain_carries_the_reference_and_not_the_rider`** and
  **`test_the_pii_gate_still_fails_closed_ahead_of_the_new_wiring`** — the
  ADR-0051 PII gate still runs first. A new field flowing through an adapter is
  exactly the change that can quietly reorder a security check.
- **`test_the_composite_and_the_outcome_cannot_disagree`** — the adapter's own
  record and the canonical `Outcome` cannot drift apart.

## Honest limitations

- This closes the chain for the **operator-export** adapter only. The other
  adapters (TIDES, GTFS-Flex, TLC, GTFS-Realtime) are unchanged; where they carry
  a vehicle reference it is still unwired.
- The reference is a **source-system string**, not a canonical typed id — the
  ADR-0035 rule that an external agency's identifiers stay plain strings. Two
  operators can use the same `run_ref` and mean different vehicles; nothing here
  disambiguates that, and nothing should until a real multi-operator case exists.
- The end-to-end test uses **synthetic** exports. No operator data exists.
