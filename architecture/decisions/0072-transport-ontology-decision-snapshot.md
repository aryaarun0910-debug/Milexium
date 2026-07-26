# ADR-0072: A transport ontology, and the attribute we refused to store

- **Status:** Accepted
- **Date:** 2026-07-26
- **Packet:** MX-ONT-DECISION-SNAPSHOT-013

## Context

Milexium could forecast in one place, solve in another, and export evidence in a
third. What it could not represent is a complete **decision episode**:

> This request arrived at 10:02; this wheelchair-accessible vehicle was expected
> free at 10:41; these three trips were mutually compatible; this assignment
> consumed two likely future pooling opportunities; the dispatcher overrode it;
> the resulting pickup was 14 minutes late.

That episode is the unit intelligence learns from, and nothing in the repo held
one. This is the connective tissue — deliberately built in a **new**
`packages/ontology/` rather than by extending `packages/canonical/`, which a
concurrent packet owned.

## Decision

10 modules, 4 SQL files, 9 tables: **28 object kinds, 23 relationship kinds, 16
event kinds, 11 action kinds.**

### Objects carry identity only — this is the decision everything rests on

`OntologyObject` has **no attribute field**, and `ontology_objects` has no
attribute column.

An attribute stored on an object would have no receipt time, so a decision
replayed at T would read whatever that attribute says **now**. That is how
leakage enters a warehouse invisibly: the row *is* correct, just not as of the
decision instant. Statelessness makes it **unrepresentable** rather than
discouraged.

The cost is real and charged deliberately: reading "the vehicle's capacity" is a
snapshot query, not an attribute access.

Relationships are rows with a validity interval, an optional probability
`weight`, and a `retracts_relationship_id`, with a legality table enforced at
construction and asserted total over the enum. **A foreign key could not carry
the vignette above** — "consumed two likely future pooling opportunities" needs
cardinality > 1, a probability, and non-destructive contradiction.

Events are receipt-stamped, hash-chained, and store `ingest_lag_seconds`; past
300s an event must name a `LateArrivalReason`. Actions are the **only** write
surface — the store exposes no generic writer — and each needs an `Authority`
holding the permission, an input snapshot *and its content hash*, alternatives, a
verifier verdict and a policy version. **A SYSTEM authority may not approve its
own recommendation.**

### `DecisionSnapshot` — five layers, because one is a claim

1. **SQL**: `receipt_time < ?` as a WHERE predicate over fixed-width ISO-8601 on
   all four streams. `_iso_utc` is *imported* from `packages/core/feature_store.py`
   rather than reimplemented, so the two point-in-time disciplines cannot drift.
2. **Construction**: a validator re-checks every item and raises
   `SnapshotLeakageError`. Redundant on purpose — two independent implementations
   of one rule.
3. **Structure**: no store reference, tuple-valued collections, no callable field,
   no clock. AST-asserted. The unfiltered audit view lives on the *store*, so a
   snapshot holder cannot reach past its own boundary.
4. **Content hash**: a computed property including `as_of`, compared before an
   action may cite the snapshot — because `model_copy(update=...)` and
   `model_construct` skip validators by design.
5. **Receipt monotonicity**: the layer nobody asked for and the one that matters
   most. Receipt times are non-decreasing per tenant, enforced in Python, by a DB
   trigger on both engines, and detectably by hash chain. The consequence is that
   `load_snapshot` **re-derives rather than caches**, which makes it a leak
   *detector* rather than a tautology.

## Consequences

**147 new tests, 0 skipped.** Full suite **2689 passed, 1 skipped, 0 failed**,
with PostgreSQL 17 and RLS running rather than skipping.

### Two mutations came back green, and both were real gaps

- **M20** — `for_training()` returning unfiltered facts stayed green. Two paths
  reach a training snapshot and only one was covered; the probe *did* call
  `for_training()`, but on an episode where every fact was trainable, **so the
  filter had nothing to remove.** The exact shape this repo keeps finding.
- **M22** — deleting the snapshot's cross-tenant check stayed green, because the
  store's own `tenant_id = ?` means it never *produces* such an item. The
  defence-in-depth check had nothing exercising it — and it matters, because
  evidence-pack readers and replay importers construct snapshots with no SQL
  predicate protecting them.

Separately, the first `test_every_ontology_table_refuses_update` reported all
nine tables unguarded — **the test was wrong**: a row-level BEFORE UPDATE trigger
does not fire on an empty table. Written the other way round it would have been
green with every trigger deleted.

## Honest limitations

- **No privilege separation.** Append-only rests on triggers the owning role can
  drop, and a test drops one and shows the forgery succeed. The repair needs a
  ledger-owner role requiring superuser; `milexium_dev` deliberately is not one.
  The exact SQL is written into the file as a deployment task.
- **The clock is a constructor seam** — one reviewable substitution that still
  cannot go backwards, but not a defence against a hostile operator of the
  process.
- **No concurrency testing.** Single-writer-per-tenant is an untested assumption.
- **Not wired into** the solver, forecaster, evidence packs or API; **no adapter
  and no migration path from `packages/canonical`.**
- This packet and MX-A-LIFECYCLE-IMMUTABILITY-012 independently reached the same
  three-layer append-only design. **They should converge.**

## What this tells us to ask the first operator

The two that should shape that conversation:

1. **Our receipt time is a proxy for their knowledge time.** If their system knew
   at 10:30 and exported at 11:00, a 10:45 snapshot correctly excludes it —
   correctly *for us*, but the dispatcher knew. Replay would systematically credit
   them with **less** information than they had, biasing every "we'd have done
   better" comparison **in our favour**. So: ask for a source-side knowledge/entry
   timestamp on every exported row, distinct from event time and export time —
   and ask whether their system records one at all. Retrofitting is impossible.
2. **8–12 weeks arriving as backfill breaks the property**, because backfilled
   receipt times equal ingest time and every snapshot over that history shares one
   boundary. Without (1), backfilled data supports outcome analysis but **not
   decision replay.**

Also ask early: whether their scheduler logs rejected candidates at all — if not,
`alternatives=()` reads as "nothing considered" when it means "unknown", which
needs a third state before any backfill.
