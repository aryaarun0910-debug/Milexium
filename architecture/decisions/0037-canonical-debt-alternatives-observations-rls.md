# ADR-0037: Clearing canonical debt — DecisionAlternative storage, StopTimeObservation persistence, RLS on the observation tables

- **Status:** Accepted
- **Date:** 2026-07-24
- **Packet:** MX-A-CANONICAL-DEBT-003

## Context

`IMPLEMENTATION_STATUS.md` has carried three flagged canonical gaps. Each now has
a consumer that needs it, so they stop being deferred:

1. **`decision_alternatives` had a table but no store method.** The table has
   existed since `schema_v0_1.sql` v0.1, but neither `SqliteCanonicalStore` nor
   `PostgresCanonicalStore` ever read or wrote it. Program I worked around this
   with a v0.1 convention — alternatives embedded in a `RECOMMENDATION` event
   payload (ADR-0009) — and ADR-0012 recorded the resulting state-transition
   check as "structurally inapplicable". So *"why not the alternatives?"*, a
   load-bearing explainability claim, had no storage behind it.
2. **`StopTimeObservation` was unpersistable.** ADR-0035 landed
   `VehicleObservation` with a PostGIS spatial round-trip but gave its sibling no
   store method at all — half the operational entity family could be constructed
   and never saved.
3. **The observation tables had no RLS policy.** `rls_postgres.sql` guards every
   other tenant-scoped table with `ENABLE` + `FORCE ROW LEVEL SECURITY`, but the
   two tables added by ADR-0035 were written *after* that file and were never
   added to it. A tenant-scoped table with no policy is exactly the false
   assurance ADR-0018 exists to prevent — and vehicle position/occupancy is the
   most sensitive operational data in the schema.

Gap 3 is a security defect that shipped in ADR-0035 and was missed in review.

## Decision

**DecisionAlternative storage** — `append_decision_alternative()` and
`decision_alternatives()` added to **both** stores with identical signatures,
preserving the deliberate mirror between the SQLite and PostgreSQL
implementations. `decision_alternatives` carries no `tenant_id` of its own (it is
tenant-scoped transitively through `schedule_runs`), so both stores resolve the
parent run under the acting tenant before inserting and raise a shared
`CrossTenantWriteError` if it is not visible. On PostgreSQL that is
belt-and-braces — the table's existing `tenant_isolation` `WITH CHECK` would
reject the write anyway — but it makes SQLite behave the same way, which is the
point of keeping the two contracts identical.

**The ADR-0009 convention is untouched and both paths coexist.** This packet
makes the table *usable*; it does not force a cutover. A non-regression test
asserts the embedded-payload path still works alongside the table and that the
hash chain is undisturbed.

**StopTimeObservation persistence** — insert + read added to
`observation_store.py` following the `VehicleObservation` pattern (disposable
`mx_<uuid>` schema, portable columns). **No geometry:** a stop-time observation
has no position of its own, and a test asserts no geometry column is added.
Predicted and observed times stay in separate columns, preserving the
ADR-0035 discipline that a prediction is never mistaken for a record.

**RLS extended** to `vehicle_observations` and `stop_time_observations` using the
identical `tenant_id = current_setting('milexium.tenant_id', true)` USING +
WITH CHECK pattern, with **`ENABLE` and `FORCE`** — `milexium_dev` owns these
tables, and a table owner bypasses RLS by default, so `ENABLE` alone would leave
the owning credential unconstrained and every isolation test would pass for the
wrong reason.

## Consequences

- **36 new tests, 0 skipped** — the Postgres and RLS tests **ran** against the
  native PostgreSQL 17, so isolation is proven rather than assumed. Coverage
  includes: `relrowsecurity` **and** `relforcerowsecurity` asserted directly from
  `pg_class` (an ENABLE-only setup fails this, rather than being inferred from
  behaviour); a raw unfiltered `SELECT` as tenant B returning none of A's rows; a
  positive control proving the block isn't passing on an empty table; unset GUC
  yielding **deny-all, not allow-all**; a foreign-`tenant_id` INSERT rejected;
  and `test_force_row_level_security_is_load_bearing_on_observations`, which
  lifts FORCE, watches the boundary collapse, and restores it.
- Both stores are parametrised `[sqlite]`/`[postgres]` on the
  `DecisionAlternative` contract, so drift between them fails loudly.
- `schema_v0_1.sql` is **unchanged** (0-line diff) and stays portable/SQLite-safe.

**Honest scope limit, recorded in the file header rather than glossed:**
`rls_postgres.sql` is applied only by `PostgresCanonicalStore` against the native
instance on 5432. `PostgisObservationStore` targets the containerized PostGIS on
5433 and applies the portable schema plus `postgis_postgres.sql`, **not** this
file — its reads are tenant-filtered in SQL but **not policy-enforced**.
Extending RLS there requires the store to set the GUC per operation and is a
separate decision, deliberately not assumed here. Anyone reading
`rls_postgres.sql` now sees that boundary stated instead of inferring blanket
coverage.
