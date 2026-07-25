# ADR-0063: The lifecycle record — making a sentence we wrote down true

- **Status:** Accepted
- **Date:** 2026-07-26
- **Packet:** MX-A-LIFECYCLE-RECORD-010

## Context

We told a former WMATA accessibility chief, in writing, that the platform

> *"records why each trip received the outcome it did — booked, offered,
> negotiated, denied or late — created at the moment of the decision rather than
> reconstructed afterwards."*

He then invited us to evaluate live agency deployments. **That sentence had to
become literally true, end to end**, or the only industry relationship we have
would not survive a demo.

Verified before this packet: `ServiceRequestState` is a real normative state
machine, `RequestTimes` keeps requested/negotiated/scheduled/predicted windows
separate, and `Denial` carries hard-constraint reason codes. Nothing was
oversold. What was **missing** was the durable per-request history — a contract
for legal transitions existed; a *record* of them did not.

## Decision

An append-only per-request transition history, persisted on both engines.

### Bitemporality is the claim, so it is enforced structurally

The load-bearing word in that sentence is **"at the moment of the decision"**, so
the record separates two times that are usually conflated:

- **`decided_at`** — *valid* time: the operational instant a dispatcher or the
  scheduler actually reached the conclusion.
- **`recorded_at`** — *transaction* time: when the row was written.

**`decided_at` has no SQL `DEFAULT` and is never defaulted anywhere on the write
path.** A record that silently stamps itself on write is precisely the
"reconstructed afterwards" thing we told him we do not do, and a default is how
that happens by accident rather than by intent. The caller must supply it.

A write whose `recorded_at` precedes its `decided_at` raises
`BackdatedRecordError` — **in Python and again as a database CHECK constraint**,
because a guard that lives only in the application is a guard that a future
direct-SQL path walks around.

`LifecycleOrderError` is kept distinct from `TransitionError`: the latter means
the *contract* forbids the move, the former that the ordering is wrong. Merging
them would lose the difference between an illegal transition and a legal one
recorded out of sequence.

Every transition is checked against `SERVICE_REQUEST_TRANSITIONS`, so the history
cannot contain a path the contract forbids — enforced at the record layer, not
only in the checker.

## Consequences

**112 tests** across the record, its RLS, and the state-machine anchors
(92 + 14 + 6), passing on both engines. Full repo suite **2337 passed, 1 skipped**
with this work in place.

Tenant isolation matches the ADR-0048/0055 pattern: `tenant_id NOT NULL`, RLS
ENABLE **and** FORCE, one policy, with the ADR-0043 empty-string case tested
explicitly and the acting role asserted non-superuser and non-BYPASSRLS before
any conclusion is drawn from a policy test.

## Honest limitations

- **Nothing here is Validated.** Every fixture is synthetic; there is no
  consented operator data, and a lifecycle record of invented trips proves the
  mechanism and nothing about any real agency.
- The history records *that* a transition happened with its reason codes; it does
  not model **who** was entitled to make it. Actor is recorded, authorisation is
  not enforced.
- `decided_at` is supplied by the caller, so the record is only as truthful as
  the system feeding it. **We can prove a record was not back-written after the
  fact relative to its own recording; we cannot prove the caller told the truth
  about when it decided.** An operator integration would need its own attestation
  for that, and this ADR does not provide one.
- Reason codes come from the fixed `ReasonCode` vocabulary. A real agency will
  have denial reasons that vocabulary cannot express, and the honest failure mode
  there is an unmappable reason rather than a wrong one — but it is a failure
  mode.
