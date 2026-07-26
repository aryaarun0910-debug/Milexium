# ADR-0012: Evidence IR state-transition check is structurally inapplicable in v0.1

- **Status:** Accepted (documents a known gap, not a resolution)
- **Date:** 2026-07-23

## Context

ADR-0009 flagged that `aletheia/evidence` originally checked hash-chain
integrity only, not schema or state-transition legality. A follow-up packet
folded in schema verification (`aletheia.verify.verify_against_schema`) but
found state-transition verification (`aletheia.verify.verify_state_sequence`)
cannot be meaningfully wired into `build_evidence_packet` given what this
repository's contracts actually provide today — not because it was skipped,
but because the necessary data doesn't exist in the builder's inputs.

`build_evidence_packet(events, raw_rows, outcome=None)` reconstructs a
narrative from a `DecisionEvent` ledger. `DecisionEvent` payloads carry no
recorded `ServiceRequestState` by any convention this repository has
established — `themis/connect`'s adapters only ever set
`status=ServiceRequestState.REQUESTED` at creation time; nothing writes
further transitions as recorded facts. A `ServiceRequest`'s own bitemporal
version history (where `status` actually changes across versions) is a
structurally different stream than the event ledger, and the builder's fixed
three-argument signature never receives it.

## Decision

Ship `EvidencePacket.state_check_applicable: bool = False` (always `False` in
this slice) and `state_violations: tuple[StateViolation, ...] = ()` (always
empty, disambiguated by the flag above — never read as "state legality
verified" on its own). Do **not** fabricate a state sequence by inferring one
from `DecisionEventType` (e.g. treating `OUTCOME_RECORDED` as implying
`COMPLETED`) — that would derive a new fact about the world rather than
reorganize an already-recorded one, which `aletheia/evidence/models.py`'s own
docstring rules out as a design principle for this package.

This is recorded as a genuine capability gap, not a completed feature with a
disabled flag — same spirit as `data/curated/`'s existing negative results (e.g.
the weather-ablation finding): the honest answer here is "this check does not
apply yet," not "this check always passes."

## Consequences

Closing this gap for real requires one of two future decisions, neither made
here:

1. A new payload convention where producers record `ServiceRequestState`
   transitions inside `DecisionEvent` payloads going forward (a new
   commitment other producers would need to honor), or
2. Accepting a separately-sourced `ServiceRequest` version history as an
   additional, optional input to `build_evidence_packet` (a signature change,
   deliberately out of scope for the packet that surfaced this gap).

Until one of those lands, any `EvidencePacket` with `state_check_applicable
== False` should be read by a reviewer as "state legality was not checked,"
not as "state legality was fine."
