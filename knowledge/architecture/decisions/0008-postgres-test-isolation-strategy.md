# ADR-0008: Per-instance disposable schema for PostgreSQL test isolation

- **Status:** Accepted
- **Date:** 2026-07-23

## Context

`app/canonical/storage.py`'s `SqliteCanonicalStore` gets test isolation
for free: each instance defaults to a fresh `:memory:` database. PostgreSQL
(ADR-0004, ADR-0006) is a real, persistent, potentially-concurrently-accessed
server — `PostgresCanonicalStore` needs an explicit isolation strategy rather
than relying on process exit to clean up.

## Decision

Each `PostgresCanonicalStore` instance creates its own PostgreSQL `SCHEMA`
(namespace) named `mx_<uuid4 hex>` at construction time, sets `search_path`
to it, and applies `app/canonical/sql/schema_v0_1.sql` (unmodified)
inside that schema. `drop_schema()` (`DROP SCHEMA ... CASCADE`) tears it down
completely. Tests use a fixture that always calls `drop_schema()` +
`close()` in a `finally` block.

Random per-instance names make collisions between concurrent test runs
structurally impossible (not just unlikely), and `CASCADE` drop guarantees no
cruft survives in the shared `milexium_dev` database even if a test fails
mid-assertion, since teardown doesn't depend on the test having succeeded.

`schema_v0_1.sql`'s full multi-statement text runs in one `psycopg` `execute()`
call without needing per-statement splitting — confirmed empirically against
PostgreSQL 17.10; if a future PostgreSQL/psycopg combination stops accepting
that, split on statement boundaries rather than changing the DDL file itself
(the DDL's portability across SQLite/Postgres, ADR-0002, is the higher-value
constraint to protect).

Both new Postgres-backed test files probe reachability at module level and
`pytest.skip(..., allow_module_level=True)` if `milexium_dev` isn't reachable,
so the suite stays green on a clone of this repo where PostgreSQL was never
provisioned.

## Consequences

- No RLS, connection pooling, or multi-tenant schema strategy is implied by
  this decision — `mx_<uuid>` schemas are a **test-only** isolation
  mechanism, not the production multi-tenancy design. Production tenant
  isolation (row-level security plus application authorization, per
  `blueprint/10-security-privacy-and-ai-governance.md`) remains Specified.
- A verification pass after two full suite runs found zero leftover `mx_*`
  schemas in `information_schema.schemata` — the teardown holds under normal
  operation; it has not been tested under process-kill/crash scenarios
  (that's a recovery-drill concern, `platform/ops/recovery/`, not yet built).
