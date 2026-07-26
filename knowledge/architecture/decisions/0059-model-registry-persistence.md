# ADR-0059: Persisting the model catalog through a FORCEd boundary

- **Status:** Accepted
- **Date:** 2026-07-25
- **Packet:** MX-D-REGISTRY-PERSISTENCE-009
- **Closes:** the in-memory `ModelRegistry` defect; exercises the hazard ADR-0055 named

## Context

`ModelRegistry` was in-memory: promotion roles survived a restart, the model
catalog did not. Closing that meant adding tables — and ADR-0055 had just
recorded that doing so was now dangerous:

> From v2 onward the tables are FORCEd, so a 2→N data-moving migration with no
> GUC in scope sees **zero rows** and "succeeds" having moved nothing. 1→2 is safe
> only because v1 predates RLS.

This packet is the first migration to face that, and its migration **counts
rows**.

## Decision

`PersistentModelRegistry` over the existing `CoreDatabase`, at schema version 3.

### Two names chosen to avoid silent absorption

- **`core_model_versions`, not `model_versions`.** `app/canonical/sql/schema_v0_1.sql`
  already owns that name, and a Program D store may legally be opened against a
  database carrying the canonical contract. **The collision would not have
  errored** — every core `CREATE` is `IF NOT EXISTS`, so whichever contract
  created it first would silently absorb the other's writes. Same reasoning that
  named the ledger `core_schema_migrations`.
- **`core_model_champions`, not `promotion_champions`.** Sharing that row would
  let `registry.promote()` install a serving champion that no `promotion_decisions`
  row authorised — making the ADR-0010 ledger incomplete for the first time.

### The zero-rows hazard, handled in three parts

The migration counts how many model versions the existing promotion state
references and the new empty catalog cannot describe. **That count is written
permanently into the ledger**, so a wrong one is a false reassurance an operator
acts on, not a wrong log line.

1. `suspend_row_level_security()` — `DISABLE` on every guarded table, plus
   `SET LOCAL row_security = off` so PostgreSQL *raises* rather than filters if
   anything was missed.
2. `_require_countable_rows()` reads `pg_class.relrowsecurity` back and raises
   `RowSecurityInForceError` if any table is still guarded. It reads
   `relrowsecurity` **alone, not force** — a force-aware check would pass for the
   owner and rest the migration's correctness on table ownership, which is
   precisely the ADR-0046 false green.
3. The restore runs **inside the migration's own transaction**, not in
   `migrate()`'s final call — `migrate()` commits between the stamp and that
   call, which would publish a committed window with nine tables unguarded.

**Proved, not asserted.** A control shows the hazard is real: a blind `COUNT(*)`
on a genuine FORCEd v2 database returns **0** while a scoped control returns
**1**. The migration then records the true count — **3** distinct ids referenced
from 8 columns across 6 tables, so a migration that counts naively or stops at one
table gets a *plausible* wrong number rather than an obviously broken one. Neuter
the suspension and it refuses; a refused migration leaves both bits TRUE after
rollback.

### A correction to the 1→2 step

1→2 now applies a preserved `legacy/core_v0_2_pre_catalog.sql` rather than the
current DDL, so **each step produces exactly its own version's shape**. While v2
and CURRENT were the same thing this was invisible; now a 1→2 step creating the
v3 shape would leave tables at 3 while the ledger said 2 — a real committed
window, and a crash there yields a `SchemaShapeMismatchError` nobody introduced by
hand. `detect_shape` now matches the table set **exactly, not as a subset**,
because v3's seven old tables match v2 column-for-column and a subset test would
re-run a completed migration.

## Consequences

**113 new tests** (33 sqlite, 33 postgres, 40 PostgreSQL-only, 7 file/signature),
0 skipped, **73 against native PG 17**. Program D surface **433 passed**; whole
repo **1832 passed, 0 failed, 0 skipped**. Five existing suites unedited;
`test_core_migrations.py` needed five edits, all forced by the version bump, none
behavioural.

`relrowsecurity` **and** `relforcerowsecurity` read TRUE on both new tables after
migrating, FALSE on the same relations after the portable DDL alone, and absent
from `pg_class` entirely on a genuine v2 database. The seven v2 tables were
asserted (True, True) *before* migrating, so the count evidence is not a fixture
artefact. `core_model_versions` carries ADR-0043's asymmetric policy — the first
Program D table genuinely exposed to the empty-string trap, tested with
`value == "" and is_null is False` explicitly.

**Mutation 8 found a defect in a test the packet had just written.** A restored
controller resolving the champion stayed green with the registry's commit
deleted — the controller shares the `CoreDatabase`, and *its* commit swept the
pending INSERT along. **The durability it appeared to prove was borrowed.**
Restructured so the catalog write commits and reopens on its own before any
controller exists.

## Honest limitations

- **Dangling references are counted and listed, but cannot be repaired.** A
  champion pointer records an id; a `ModelVersion` also needs a manifest hash,
  schema version, evaluation window and artifact hash — none of which exists in
  the v2 schema. This is a **real user-visible regression**: a restored controller
  refuses operations the old in-memory-plus-re-registration path allowed.
- **The migration does not refuse on a non-zero count.** Refusing would leave
  every existing database unopenable with no argument the caller could pass — a
  dead end, not a decision point. If recording is too quiet, the fix is a required
  acknowledgement argument, not a silent default.
- **`RowSecurityInForceError` is raised from `apply`, not `precheck`, so
  ADR-0055's "a refused database is left byte-identical" does NOT hold for it** —
  the `adopted` stamp is already committed. The database is left consistent at v2
  and a retry resumes. Do not quote the stronger claim for this refusal.
- **The suspension lowers a real boundary.** It grants nothing (the connection
  owns the tables) and is never committed unguarded — but it is the first in this
  repo, and **a future migration copying the mechanism without the guard and the
  in-transaction restore would have the hole without the safety.**
- **Model version ids are unique per tenant, not globally.** `_find` asks
  own-tenant before platform so collisions resolve in the customer's favour; the
  narrow race is not prevented.
- **No unscoped catalog view.** `ModelRegistry.list_for_task()` returns every
  version regardless of owner; the persistent one cannot. Signature parity holds,
  that behaviour does not.
- **`get()` now answers "not registered" for "not yours"** — closes an ADR-0043
  gap for the persistent path, but the two backends now raise under different
  conditions.
- `SET LOCAL row_security = off` is **untested and unreachable** while `DISABLE`
  precedes it and the Python guard runs first. It exists for a table added to the
  RLS file and missed by `ALL_CORE_TABLES`.
- Shape detection still compares **column names only**; the new index is not part
  of any detected shape.
- Cross-tenant registration order rests on a **wall-clock timestamp**.
