# ADR-0048: Tenant isolation for Program D — and the test RLS would have made vacuous

- **Status:** Accepted
- **Date:** 2026-07-25
- **Packet:** MX-D-TENANT-ISOLATION-006
- **Closes:** the gap recorded in ADR-0041's limitations

## Context

ADR-0041 made Program D persistent and named the consequence honestly: the seven
new tables (`feature_values`, the promotion ledger and its role tables) had **no
tenant column and no row-level security**. Every other tenant-scoped table in
this repo is guarded (ADR-0018/0037/0043/0046/0047). A second operator's feature
values and promotion history would have shared those tables with nothing between
them.

## Decision

`tenant_id TEXT NOT NULL` on all seven tables, leading every primary key and the
as-of index, plus a Postgres-only `packages/core/sql/core_rls_postgres.sql`
(`ENABLE` + `FORCE` + the `milexium.tenant_id` GUC policy per table). `tenant_id`
enters the stores via the constructor; the GUC is set per operation.

**The leakage guarantee composes rather than being replaced.** ADR-0041's
load-bearing invariant is the strict `knowledge_time < as_of` SQL predicate.
`tenant_id = ?` is an **additional conjunct beside it, never a substitute** —
proved three ways: a cross-tenant as-of read at a deliberately permissive
timestamp returns nothing *with a positive control proving that timestamp would
have admitted it*; an own-tenant read at exactly the stamp still returns the
prior value; and on the real AAR panel, a second tenant flooding the same
`(entity, feature)` with garbage at every knowledge time leaves tenant A's every
past read bit-identical, with a control proving B's rows really are there and
really are different.

## The finding: RLS would have made an existing test vacuous

ADR-0041's in-place-corruption test — the one that only a *persistent* store can
be asked to pass — issues a raw SQL `UPDATE` over stored values, then reopens the
connection and asserts past reads are bit-identical.

**Under RLS, that `UPDATE` issued with the wrong (or no) tenant in scope silently
matches ZERO rows.** The test would still have passed — and would have been
proving nothing at all, because "the past didn't change" is trivially true when
the tamper never happened. A green suite would have been asserting emptiness.

The packet hardened it: the test now asserts the tamper **landed** (a read after
the cutoff must *see* the corruption) before the bit-identical assertions are
allowed to mean anything. This is the same class of defect as ADR-0046's
superuser — a boundary change that quietly turns a real test into a tautology —
and it is why "all tests still pass" is a weaker signal than it looks after a
security change.

**Both previously-documented traps were closed by construction, not by luck:**

- The acting role is asserted **non-superuser, non-BYPASSRLS, and table owner**
  before any isolation result is claimed, so FORCE is provably load-bearing
  (ADR-0046's finding, applied pre-emptively).
- The RESET case asserts `value == "" and is_null is False` **explicitly** before
  asserting deny-all, and no clause in the RLS file is written as `IS NOT NULL`
  — the two occurrences of that string are comments explaining why it is not used
  (ADR-0043's empty-string trap).

## Consequences

- **150 tests, 0 skipped** (89 new isolation cases + 61 persistence). **81 ran
  against native PostgreSQL 17.** `relrowsecurity` **and** `relforcerowsecurity`
  asserted from `pg_class` for all seven tables; FORCE lifted per table shows the
  boundary collapse and its return.
- **Sequences are now per-tenant — forced, not stylistic.** Under RLS the `MAX()`
  that assigns them only sees the acting tenant's rows, so a global counter would
  collide on the primary key for the second operator.
- `DROP POLICY IF EXISTS` precedes each `CREATE POLICY` (unlike
  `rls_postgres.sql`) because `CoreDatabase.postgres(schema=...)` *reopens* a
  named schema and `CREATE POLICY` is not idempotent.
- `core_v0_1.sql` verified portable by executing its own bytes twice against a
  bare `sqlite3` in-memory connection.

**Honest limitations:**

- **The in-memory reference classes stay tenant-free.** The gap was a shared
  *table*; a dict key is not a boundary. Adding the parameter would also break
  the method-parity check, which excludes constructors.
- **No migration path.** Every `CREATE` is `IF NOT EXISTS`, so a pre-tenant
  ADR-0041 database is not upgraded by reopening. Acceptable **only** because
  these tables have never held operator data — and that ceases to be true the
  moment they do.
- **SQLite has no policy and cannot have one.** There the boundary is the stores'
  predicates alone — application code, not a database boundary.
- **The controller still does not check `ModelVersion.tenant_id`.** The correct
  rule is "own tenant OR platform" (ADR-0040/0043), which is a
  `model_registry.py` decision owned by a concurrent packet. Exposure is bounded
  (in-process registry, no row crosses the DB boundary) but it is named rather
  than half-fixed.
- The GUC is set per operation rather than cached — a cache was rejected because
  anything sharing the connection can move it, and a stale value reads the wrong
  tenant.
