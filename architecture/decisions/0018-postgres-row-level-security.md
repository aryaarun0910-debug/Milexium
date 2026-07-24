# ADR-0018: PostgreSQL row-level security for tenant isolation (Program C)

- **Status:** Accepted
- **Date:** 2026-07-24

## Context

`PostgresCanonicalStore` (ADR-0004/0008) filtered by `tenant_id` in SQL WHERE
clauses — application-layer isolation only. Before any real customer data
touches Postgres, `blueprint/10-security-privacy-and-ai-governance.md` requires
isolation enforced at the database layer ("Database row-level security plus
application authorization"), and adversarially tested. It also warns:
"Database owners can bypass typical RLS behavior."

## Decision

`packages/canonical/sql/rls_postgres.sql` (Postgres-only, separate from the
portable `schema_v0_1.sql` which stays SQLite-compatible) applies to all 12
tenant-scoped tables:

- `ENABLE` **and `FORCE` ROW LEVEL SECURITY** — `FORCE` is load-bearing: the
  `milexium_dev` role owns the tables, and a table owner bypasses plain RLS,
  which would make the isolation test a false green. `FORCE` binds the owner
  too, and the role (verified) has neither superuser nor `BYPASSRLS`.
- A `tenant_isolation` policy with both `USING` (reads/updates/deletes) and
  `WITH CHECK` (inserts) testing `tenant_id = current_setting('milexium.tenant_id', true)`.
- The GUC is read with `missing_ok=true` so an **unset session is deny-all**
  (NULL matches nothing), never allow-all.
- `decision_alternatives` has no `tenant_id` column → scoped transitively via a
  subquery through `schedule_runs`. `tenants` is scoped to itself (a session
  sees only its own row; listing all tenants is a platform-admin op needing a
  dedicated `BYPASSRLS` role, out of scope for v0.1).

The store sets the GUC via `set_config('milexium.tenant_id', <tenant>, false)`
(bound parameter, session scope) as the first statement of each tenant-scoped
method. **Session scope, not `SET LOCAL`**, was deliberate: the pre-existing
tamper/isolation tests manipulate the raw connection without setting a GUC, and
transaction-local reset would break them (a duplicate insert would raise
`InsufficientPrivilege` instead of the expected `UniqueViolation`). Every
method re-sets the GUC before querying, so isolation holds regardless of prior
state.

## Consequences

- **Proven, not asserted**: `test_postgres_rls_isolation.py` issues a raw
  `SELECT` over the whole table (no Python WHERE) under tenant B's GUC and gets
  zero of tenant A's rows; flipping `NO FORCE` makes the owner see all again
  (proving FORCE is what enforces it); an unset session sees nothing.
- RLS is defense in depth on top of the existing application filtering, not a
  replacement — both hold.
- `model_versions`/`forecast_vintages` are guarded by the same policy, but
  platform-trained models belong to no single tenant (ADR-0010's open
  question) — safe for now (no store method reads them), reconcile when the
  platform-tenant convention is chosen.
- Referential-integrity checks bypass RLS by design (Postgres behavior) — noted
  for any future cross-table constraints.
- Not built (Specified): the `BYPASSRLS` platform-admin role, key management,
  encryption at rest, backup/restore drills.
