# ADR-0009: Evidence IR v0.1 conventions (alternatives-in-payload, executed-event rule)

- **Status:** Accepted
- **Date:** 2026-07-23

## Context

`blueprint/07-explain-replay-and-evidence.md`'s Program I integration proof
requires that "an independent reviewer can reconstruct what was known,
proposed, verified, approved, executed, and observed" from an aggregate's
recorded history alone. `packages/evidence` builds this reconstruction
(`EvidencePacket`) purely from an already-recorded `DecisionEvent` history,
raw storage rows, and an optional `Outcome` — never a live store connection,
so the same builder works against either storage backend (SQLite today,
PostgreSQL per ADR-0008).

Two gaps in the existing Program A contract required a v0.1 convention
rather than a contract change:

1. `packages/canonical/sql/schema_v0_1.sql` has a `decision_alternatives`
   table, but `packages/canonical/storage.py`/`postgres_storage.py` expose no
   read/write method for it — Program A never got a store method for
   alternatives, only a schema definition.
2. Nothing in Program A designates which of several `RECOMMENDATION`/
   `OVERRIDE` events in a chain is the one that actually stood.

## Decision

- **Alternatives via payload, not a separate table read**: a producer that
  wants `DecisionAlternative`s to appear in an `EvidencePacket` embeds them in
  a `RECOMMENDATION` event's `payload["alternatives"]` as a list of dicts,
  each parseable via `DecisionAlternative.model_validate(item)`. This is a
  convention **owned by `packages/evidence`**, not a change to
  `packages/canonical`'s contract or its `decision_alternatives` table. If
  Program A later adds a real store method for that table, this convention
  should be reconciled against it rather than kept as a permanent parallel
  path — flagging this explicitly so it isn't forgotten.
- **`executed` derivation rule**: the chronologically last event (by
  `sequence`) of type `RECOMMENDATION` or `OVERRIDE`. A later `OVERRIDE`
  supersedes an earlier `RECOMMENDATION`; absent any override, the
  recommendation stands. `build_evidence_packet` sorts events by `sequence`
  itself rather than trusting caller order, matching `verify_chain`'s own
  stance of not trusting input ordering.
- **Raw rows are filtered to the packet's own `aggregate_id`** before calling
  `packages.verify.verify_chain`, so a caller can pass a whole tenant's
  `raw_rows_for_tenant()` output without an unrelated aggregate's violations
  leaking into this packet's `chain_violations`.
- **`build_experience_packet` refuses to run** if `packet.integrity_verified`
  is `False`, or if a passed-in `Outcome` disagrees with one the packet
  already carries — an unverified chain must never become a precedent record,
  consistent with the hash chain being "tamper-evident, not immutable and not
  a compliance certificate" (`blueprint/01-north-star-and-boundaries.md`).
- No prose/natural-language rendering was added in this slice. `EvidencePacket`/
  `ExperiencePacket` are the record; if a rendered view is built later, it must
  consume these packets rather than replace them, per the same document's
  "a generated natural-language explanation is never the authoritative
  decision record."

## Consequences

- `packages/evidence` currently only checks hash-chain integrity
  (`verify_chain`), not schema or state-transition legality
  (`verify_against_schema`, `verify_state_sequence`) — folding those in is
  straightforward future work, not a redesign, if a later packet needs it.
- The alternatives-via-payload convention is the most likely piece of this
  slice to need revisiting once a real scheduler actually writes
  `decision_alternatives` rows — this ADR is the record of why it exists and
  what would supersede it.
