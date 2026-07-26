# ADR-0055: Program D migrations — and refusing to invent a tenant

- **Status:** Accepted
- **Date:** 2026-07-25
- **Packet:** MX-D-MIGRATIONS-008
- **Closes:** the "no migration path" limitation recorded in ADR-0048

## Context

ADR-0048 added `tenant_id NOT NULL` to Program D's seven tables and recorded the
consequence plainly: every `CREATE` is `IF NOT EXISTS`, so a database created
before that change is **not** upgraded by reopening it. It called this
"acceptable **only** because these tables have never held operator data" — and
noted it stops being acceptable the moment they do.

A design partner's export is exactly the event that ends it, and the current
outreach exists to cause that event.

## Decision

A real migration mechanism: a version ledger
(`core_schema_migrations`), a preserved copy of the version-1 schema, an ordered
idempotent chain, and **loud refusal** on an unknown or newer version.

### Refusing to invent a tenant is the decision

If any of the seven tables holds a row and no `legacy_tenant_id` was supplied,
the migration raises `LegacyTenantRequiredError` naming every populated table and
its count. **It does not choose**, because each candidate default is wrong in a
way that surfaces late:

- an **invented UUID** names nobody and orphans the data;
- the **ADR-0040 platform tenant** would declare an operator's private feature
  values and promotion ledger platform-owned — and platform-owned rows are
  readable by *every* tenant, so **the innocuous-looking default is the leaking
  one**;
- the **empty string** is precisely the value `core_rls_postgres.sql`'s deny-all
  default assumes no row ever holds.

When a tenant *is* declared it is validated as a canonical `TenantId` in the
precheck — before anything is written — and recorded permanently in the ledger
note. An **empty** version-1 database, the only case ADR-0048 claims ever
existed, migrates silently and records that none was invented.

### RLS survives the migration, and that is the dangerous part

The table-rebuild technique that makes the migration portable is exactly what
endangers the boundary: **a rebuilt table is a new relation, and ENABLE/FORCE/
policy do not follow the rows into it.** `migrate()` therefore re-applies
`core_rls_postgres.sql` at the end of every PostgreSQL run — **after** the copy,
because before it `WITH CHECK` would reject every row and the migration would
move nothing while reporting success.

Proved rather than asserted: `relrowsecurity` **and** `relforcerowsecurity` read
TRUE from `pg_class` for all seven rebuilt tables — with the same two bits
asserted **FALSE on the same tables before migrating**, so the result is evidence
about the migration and not about the fixture. Plus one policy per table, raw
cross-tenant reads returning nothing with positive controls, cross-tenant writes
refused, a FORCE-lift showing the boundary collapse and return, the RESET-GUC
empty-string case asserted explicitly (ADR-0043's trap), and the acting role
asserted non-superuser, non-BYPASSRLS and **owner** first.

## Consequences

- **109 tests, 0 skipped**; 76 ran against native PostgreSQL 17. With the two
  existing suites, **259 passed** — and neither existing suite was edited.
- Two findings surfaced during the work and were fixed rather than worked around:
  three tests initially failed because a post-migration raw read with no GUC in
  scope returned zero rows — *the policy working*; and the tenant refusal
  originally fired **after** the version-1 stamp was committed, so every pending
  migration's `precheck` now runs before the first write, with a test proving a
  refused database is left byte-identical.
- The ledger is deliberately named `core_schema_migrations`, not
  `schema_migrations`: a Program D store can be opened against a database that
  also carries the canonical contract, and two ledgers sharing a table name would
  each read the other's rows as its own.

**Honest limitations:**

- **A future data-moving migration on PostgreSQL will hit RLS.** From v2 onward
  the tables are FORCEd, so a 2→N migration that counts or copies rows with no
  GUC in scope sees zero rows and "succeeds" having moved nothing — the same
  vacuity class ADR-0048 found in the corruption test. 1→2 is safe only because
  v1 predates RLS. Named in the module, the packet and the RLS file.
- **Atomicity is claimed on PostgreSQL only.** On SQLite a crash mid-rebuild
  leaves rows in `mx_core_v1_*` and the next open **refuses**, naming them — a
  safety net, not a transaction.
- Shape detection compares **column names only**; a migrated Postgres table is
  behaviourally identical but not catalog-identical (its PK constraint is
  `feature_values_pkey1`).
- One refusal branch is unreachable while versions 1 and 2 are contiguous.
- No locking, no downgrade; the declared tenant is validated as well-formed, not
  as existing.

**Follow-up, deliberately not fixed:** `app/canonical/sql/schema_v0_1.sql`
has the same class of problem and is worse in one respect — its `CREATE TABLE`s
carry no `IF NOT EXISTS` at all, so re-applying errors. That sounds safer but
isn't: the canonical stores sidestep it by always creating a *fresh* schema, so
**the canonical contract has never had to answer what happens to an existing
database when the schema changes.**
