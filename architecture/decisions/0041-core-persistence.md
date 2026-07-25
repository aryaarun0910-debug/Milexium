# ADR-0041: Program D persistence — the leakage guarantee survives the database

- **Status:** Accepted
- **Date:** 2026-07-25
- **Packet:** MX-D-PERSISTENCE-004

## Context

ADR-0034 landed Program D's adaptive-memory slice — the leakage-safe
point-in-time feature store, the champion/challenger/canary promotion
controller, and drift detection — as **in-memory reference backends only**. A
design partner's feature values, promotion decisions and rollback history would
not survive a process restart. That is the gap a real pilot hits first, and it
was named honestly in ADR-0034's limitations.

## Decision

A portable Program D schema in a **new** `packages/core/sql/core_v0_1.sql`
(`packages/canonical/sql/schema_v0_1.sql` is a different contract and was not
touched), plus `PersistentFeatureStore` and `PersistentPromotionController`
exposing the **same contract** as the in-memory classes, which remain the
reference implementation and are unchanged.

**The leakage guarantee is enforced by the database, not around it.** The
load-bearing invariant is that an as-of read at label time `t` returns only
values whose `knowledge_time` is strictly `< t`. That is now a **SQL predicate**
(`WHERE knowledge_time < ?`) over fixed-width canonical ISO-8601 UTC text — a
future row is never fetched, rather than fetched-and-then-filtered. The
distinction matters: a filter applied after retrieval is a correctness property
of application code that a future refactor can quietly break; a predicate is a
property of the query.

**`DOUBLE PRECISION`, not `REAL`.** SQLite's `REAL` is a 64-bit IEEE double, but
PostgreSQL's `REAL` is **float4**. Declaring `REAL` would mean the same write
read back at different precision on the production engine than on the reference
one — silently breaking the bit-identical claim that the whole leakage proof
rests on, and only on the engine that matters. Verified via
`information_schema`, with a test asserting exact `==` round-trip of `math.pi`,
`0.1+0.2` and `1e-300`.

**One store over an engine-parametrised `CoreDatabase`, not two copied classes.**
`packages/canonical` has two implementations because its PostgreSQL half carries
RLS the SQLite half cannot express. Program D has no tenant dimension, so the
only differences are the placeholder style and the connect path. The pattern's
actual assertion — one contract, two engines, `[sqlite]`/`[postgres]`
conformance — is preserved; a duplicate that could only drift is not.

A promotion role change and its ledger row **commit in one transaction**, so no
champion can exist without a recorded decision.

## Consequences

**57 tests** (27 × `[sqlite]`/`[postgres]` + 3 structural); suite 781 → 838.
The Postgres parameters **ran, not skipped** — 28 passed, 0 skipped against the
native PostgreSQL 17, one disposable `mx_core_<uuid>` schema per test with
`DROP SCHEMA ... CASCADE` teardown, still skipping cleanly when the instance is
absent so CI stays green. ADR-0034's original 52 tests pass unchanged.

The leakage guarantee is proved three ways on the real AAR panel, on both
engines:

1. **Rebuild-from-corrupted** — the ADR-0034 discipline, at three cutoffs.
2. **In-place corruption** — the version only a *persistent* store can be asked
   to survive: raw-SQL `UPDATE` of every stored post-cutoff value, connection
   dropped and reopened, all past reads still bit-identical.
3. **Control** — a post-cutoff read *does* change, so the bit-identity above is
   not an inert no-op.

Plus a boundary test (`as_of` exactly at a stamp sees the prior value) and a
differential test against the in-memory reference on a grid including the exact
stamps.

**Honest limitations:**

- **Persistence, not concurrency.** Sequence columns are read-then-insert:
  correct for a single writer, racy for several — the same stance as canonical
  `decision_events.sequence`.
- **No tenant column or RLS on Program D tables.** Multi-tenant Program D state
  is a later slice; today these tables are not tenant-isolated, and that must be
  closed before a second operator's data lands in them.
- **`ModelRegistry` remains in-memory.** Promotion *roles* survive a restart;
  the model *catalog* does not, so callers must re-register `ModelVersion`s on
  startup. Named, not hidden.
- ADR-0034's coexistence stands — the controller still does not sync the
  registry's ADR-0010 champion pointer.
- Real-panel leakage tests window the AAR panel to its first 300 observed days
  so the Postgres parameter runs in seconds; the invariant is per-(entity,
  feature) and holds pointwise.
- `core_v0_1.sql` is loaded by module-relative path and is not declared
  setuptools package-data — identical pre-existing exposure to
  `schema_v0_1.sql`; fixing it requires `pyproject.toml`, which this packet did
  not own.

Status: **Demonstrated**.
