# platform/contracts/sql/

The authoritative persistence DDL is **not** duplicated here — it lives at
[`app/canonical/sql/schema_v0_1.sql`](../../../app/canonical/sql/schema_v0_1.sql)
(the portable SQLite/PostgreSQL subset, ADR-0002/0004) plus
[`app/canonical/sql/rls_postgres.sql`](../../../app/canonical/sql/rls_postgres.sql)
(the PostgreSQL row-level-security policies, ADR-0018).

They are referenced from the contract layer here rather than copied so there is
a single source of the persistence invariant. When the Rust data plane owns
migrations (deferred, ADR-0026), the migration tool reads those same files.
