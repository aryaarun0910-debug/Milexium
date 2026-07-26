# ADR-0038: Operator data intake — the path from "yes" to data

- **Status:** Accepted
- **Date:** 2026-07-24
- **Packet:** MX-C-OPERATOR-INTAKE-003

## Context

Fifteen US transit agencies were cold-emailed on 2026-07-24 offering a free
analysis of their own trip data. If one says yes, there was **no documented way
for them to send it**: no stated format, no minimum field list, no privacy terms,
no retention story pointed at operator data. That gap — not model quality, not
breadth — is what blocks the **Validated** status gate, which requires consented
operator data by definition (ADR-0001).

## Decision

Two artifacts, deliberately split by audience.

**`forge/knowledge/docs/OPERATOR_DATA_INTAKE.md`** — what an ops director and their counsel
actually read. It opens with two honesty statements (no operator customers, no
track record, *"you would be the first"*; and this document is **not** an
agreement and cannot create one), then puts **"WHAT WE DO NOT WANT"** as §1,
before the field list — because that is the section a lawyer reads first. §8
states plainly which parts are code and which are promises.

**`themis/connect/operator_export.py`** — a generic operator trip-export
adapter against the existing `SourceAdapter` contract (ADR-0007), matching the
sibling adapters' quarantine and semantic-loss discipline.

**Field list — 10 columns, 6 mandatory:** `trip_ref`, `requested_at`,
`scheduled_pickup_at`, `actual_pickup_at` (mandatory when `outcome=served`),
`pickup_zone`, `dropoff_zone`, `vehicle_ref`/`run_ref` (at least one),
`outcome` ∈ {served, no_show, denied, cancelled}, `rider_ref` (optional, hashed,
recommended omitted). `vehicle_ref`-or-`run_ref` is mandatory because **deadhead
is only measurable by chaining one vehicle's consecutive trips** — a trip naming
neither is unusable by the downstream teardown (ADR-0039).

**Fail-closed on PII — the load-bearing invariant.** A row carrying a direct
identifier is **quarantined**, not imported-and-ignored, and the check runs
**before any other validation** so PII beats every other defect. Three layers:
column-name classification (fires even when that column is blank in the sampled
row — an all-blank `rider_name` in a sample is a populated one in the full
extract), value inspection (an email defeats renaming `email` → `contact_1`), and
zone-shape checking (a `pickup_zone` of "48 Willow Bank Road"). False-positive
tests assert `route_name`/`zone_name`/`stop_name` do **not** trip, because a
fail-closed gate that fires constantly is one people route around.

**Two deliberate deviations from sibling behaviour, both recorded:**

1. **The quarantined raw row is redacted, not verbatim.** `QuarantinedRow`'s
   contract preserves the source row; here that would copy a rider's name into
   whatever sink the caller writes quarantines to. Only offending values are
   replaced; the rest stays verbatim so the row is still fixable and re-runnable.
2. **Unmapped extension columns record the name only, `source_value=None`** —
   siblings record values. An unrecognised column in an operator export is
   precisely where unanticipated PII hides. ADR-0007 is satisfied (nothing is
   silently dropped) without retaining unknown content.

Terminal `status` is materialised directly from `outcome` rather than the
siblings' `REQUESTED`, with a `coerced` loss recording that the lifecycle
transitions happened in the operator's system and were never observed — the
aggregate's endpoint is known, its history is not replayable.

## Consequences

- **107 tests**, including 22 parametrised PII column cases plus redaction,
  blank-column, PII-beats-all-other-defects, laundering-through-`column_map`, and
  false-positive coverage. Proven against two structurally different **synthetic**
  exports (wide vendor-style and minimal) so it is not overfitted to one shape.
- Program C gains the intake half of the design-partner funnel; the teardown
  (ADR-0039) consumes exactly this adapter's output.

**Honest limitations, stated in both the code and the document:**

- **The adapter is a backstop, not a PII scanner.** It catches columns that
  announce themselves and emails that look like emails. A rider's name in a
  column called `ref2` is not caught. *The document is the contract; the code is
  the seatbelt.*
- **`rider_ref` hashing is unsalted** (matching siblings) — brute-forceable over
  a small id space by anyone holding the client list. It is a pseudonym, not
  anonymisation, and not automatically outside the agency's privacy obligations.
  No unused salt parameter was added to imply otherwise; instead the field is
  optional and the document says to omit it.
- **The address heuristic is narrow by design** (needs a leading house number
  *and* a street-type token), so `Zone 12` and `90210` pass. `Apt 4B, 12 Elm Road`
  would slip through.
- **Naive timestamps are treated as UTC** (repo-wide simplification), recorded as
  a `coerced` loss on every row.
- **§4/§5 are commitments, not automation.** There is no scheduled-deletion job
  and no access-control system beyond the RLS already built (ADR-0018/0037).
- **The signed agreement, contracting entity, secure transfer mechanism, and the
  operator-side privacy assessment are founder/legal tasks** this packet does not
  complete. §7 carries the checklist.

**Canonical gap surfaced (a Program A follow-up, flagged not papered over):**
`vehicle_ref`/`run_ref` has **no canonical home**. It is carried on the
Connect-layer `OperatorTripRecord` only and recorded as a `dropped` loss on every
row. It survives the handoff to the teardown in memory but would **not** survive
a write to MilexiumDB — so the exact field deadhead measurement depends on cannot
currently be persisted canonically. Closing that belongs to a Program A packet.
