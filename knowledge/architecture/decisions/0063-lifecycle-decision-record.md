# ADR-0063: The lifecycle record — making a sentence we wrote down true

- **Status:** Accepted — **but two central claims below were found FALSE by
  external audit on 2026-07-26. See the correction immediately below before
  relying on anything in this ADR.**
- **Date:** 2026-07-26
- **Packet:** MX-A-LIFECYCLE-RECORD-010
- **Superseded in part by:** MX-A-LIFECYCLE-IMMUTABILITY-012

## ⚠️ CORRECTION (2026-07-26, same day) — this ADR overclaimed twice

An external audit (`MILEXIUM_INTERNAL_AUDIT_2026-07-26.md`) found two P0 defects,
both confirmed independently. **Both are claims this document makes.**

**1. `recorded_at` is caller-supplied, so it is not transaction time.**
`record_lifecycle_transition` takes *both* clocks as required arguments, and the
only database constraint is `CHECK (recorded_at >= decided_at)`. The auditor
inserted a transition with `decided_at = 2020-01-01` and `recorded_at` one second
later; it was accepted. **The system proves only that two caller assertions are
ordered** — it never establishes when the row entered Milexium. The limitation
recorded below ("we can prove a record was not back-written *relative to its own
recording*") is therefore hollow, because that clock is caller-controlled too.
"Refuses backdating" is false as a general statement.

**2. "Append-only" was a coding convention, not a database invariant.** The
auditor wrote a valid denial, issued a direct SQL `UPDATE` changing `actor_id`,
committed it, and read the forged actor back through the normal lifecycle API
with no violation reported. There was no immutability trigger, no privilege
boundary, and no hash chain on this table — while the *decision-event ledger* has
all three, which let the ledger's credibility bleed onto this record misleadingly.

**The failure was one of consistency, not ignorance.** This packet's own commit
message argued that *"a guard living only in the application is a guard a future
direct-SQL path walks around"* — and then left append-only as exactly that. The
argument was made correctly about backdating and not applied to immutability.

Being the record that answers *"what happened, who decided, and when?"* is
precisely why this is P0 rather than a nice-to-have.

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
