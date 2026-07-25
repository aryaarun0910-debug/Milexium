-- PostgreSQL row-level security for the PROGRAM D tables, contract v0.1.
-- Packet MX-D-TENANT-ISOLATION-006, closing an ADR-0041 limitation.
-- Companion to packages/canonical/sql/rls_postgres.sql (ADR-0018/0037/0043/0046),
-- whose pattern this file follows deliberately rather than inventing a second one.
--
-- WHY THIS FILE IS SEPARATE FROM core_v0_1.sql
-- `core_v0_1.sql` is the *portable* DDL: it must run unmodified on SQLite (the
-- demo/reference engine) and on PostgreSQL 17 (the pinned production target), so
-- it may not contain any Postgres-only construct. RLS is Postgres-only, so it
-- lives here and is applied ONLY by `CoreDatabase.postgres(...)`, after the
-- portable schema, inside the same disposable schema (search_path already set),
-- so the unqualified table names below resolve to it.
--
-- WHAT THIS CLOSES. ADR-0041 landed feature_values and the six promotion tables
-- with no tenant column and no policy, and said so: "multi-tenant Program D state
-- is a later slice; today these tables are not tenant-isolated, and that must be
-- closed before a second operator's data lands in them." Every other tenant-scoped
-- table in this repository is guarded. A second operator's feature values and
-- promotion ledger would otherwise have sat in the same tables with nothing but
-- application WHERE-clauses between them -- and a WHERE clause is application
-- code, while a policy is a boundary.
--
-- THE OWNER-BYPASS PROBLEM (the same trap rls_postgres.sql documents).
-- `milexium_dev` OWNS every table `CoreDatabase.postgres()` creates -- it creates
-- the `mx_core_<uuid>` schema itself -- and a table owner BYPASSES RLS by default.
-- `ENABLE ROW LEVEL SECURITY` alone would therefore not constrain a single one of
-- this repository's own connections, and every isolation test would pass for the
-- wrong reason (a false green). `FORCE ROW LEVEL SECURITY` subjects the owner to
-- the policy too. `milexium_dev` is not a superuser and does not hold BYPASSRLS
-- (ADR-0006), and cannot grant itself either without a superuser, so FORCE is
-- genuinely load-bearing here:
-- conformance/property-tests/test_core_tenant_isolation.py asserts BOTH bits out
-- of pg_class, and lifts FORCE to watch the boundary collapse and come back.
--
-- THE SESSION KEY. Every policy keys on the custom session setting
-- `milexium.tenant_id`, the SAME GUC the canonical stores use, so one connection
-- carrying both contracts cannot be scoped to two different tenants at once.
-- `current_setting('milexium.tenant_id', true)` reads it with missing_ok=true, so
-- an UNSET session yields SQL NULL and `tenant_id = NULL` is never true: the
-- default is DENY-ALL, not allow-all. `CoreDatabase.use_tenant()` sets it via
-- `set_config(..., false)` (session scope) before any read or write.
--
-- THE EMPTY-STRING TRAP, and why every clause below is written as an equality.
-- `current_setting(name, true)` returns NULL only when the GUC was NEVER set in
-- the session; after `RESET` (or `SET x = ''`) it returns the EMPTY STRING, which
-- an `IS NOT NULL` guard happily accepts. No clause in this file is written as
-- `IS NOT NULL` for exactly that reason: each is `tenant_id = <the GUC>`, which is
-- false for both NULL and '' as long as no row's tenant_id is the empty string --
-- and `tenant_id` here is always a canonical UUIDv7 `TenantId` string, never ''.
-- That is an accident of the value space rather than a constraint, so the test
-- suite pins BOTH halves: that a reset session really does read back '', and that
-- deny-all holds anyway.
--
-- NO ASYMMETRIC POLICY HERE. rls_postgres.sql has one (model_versions, ADR-0040:
-- platform-owned models readable by every tenant, writable by none). Nothing in
-- Program D's runtime state is platform-owned -- a feature value and a promotion
-- decision belong to the operator whose data produced them -- so every policy
-- below is symmetric: what you may read, you may write. `USING` governs which
-- existing rows are visible (SELECT/UPDATE/DELETE); `WITH CHECK` governs which new
-- rows are permitted (INSERT/UPDATE), so a session acting as tenant B cannot even
-- write a row stamped with tenant A's id.
--
-- WHY `DROP POLICY IF EXISTS` FIRST, unlike rls_postgres.sql.
-- `PostgresCanonicalStore` always creates a fresh schema, so it applies its RLS
-- file exactly once. `CoreDatabase.postgres(schema=...)` deliberately REOPENS a
-- named schema -- that is how "state survives a restart" is tested at all -- so
-- this file is applied more than once against the same tables. `ALTER TABLE ...
-- ENABLE/FORCE` is idempotent; `CREATE POLICY` is not, and would abort the reopen
-- with "policy already exists". The drop-then-create keeps this file idempotent in
-- the same sense every `CREATE ... IF NOT EXISTS` in core_v0_1.sql is, which is a
-- precondition of the persistence claim rather than a stylistic preference.
--
-- WHEN THIS FILE IS APPLIED, AND WHY THE ORDER IS LOAD-BEARING
-- (MX-D-MIGRATIONS-008). `packages/core/migrations.migrate()` applies this file
-- at the END of every PostgreSQL run -- whether or not a migration ran. That is
-- not belt-and-braces. Migrating REBUILDS tables (SQLite can neither add a NOT
-- NULL column nor change a primary key in place, so the one portable technique
-- is rename-aside / create / copy / drop), and a rebuilt table is a NEW
-- RELATION: `relrowsecurity`, `relforcerowsecurity` and the policy below do NOT
-- follow the data through. A migration that stopped after copying the rows
-- would leave seven tables full of real operator data with tenant isolation
-- silently REMOVED -- strictly worse than the un-migrated database it started
-- from, and green on any test that only checked the rows arrived.
-- conformance/property-tests/test_core_migrations.py therefore re-asserts both
-- pg_class bits and a blocked cross-tenant read AFTER migrating, not only after
-- a fresh create.
--
-- And the rows are copied BEFORE this file runs, never after: the WITH CHECK
-- half of every policy below rejects any row whose tenant_id does not equal the
-- session GUC, and no GUC is set during a migration. Reversed, the copy would
-- move nothing while reporting success.
--
-- ONE PROGRAM D TABLE IS DELIBERATELY ABSENT FROM THIS FILE:
-- `core_schema_migrations`, the schema-version ledger. It holds no operator
-- data -- it records which shape the database is in -- and putting it under a
-- tenant policy would be actively dangerous rather than merely redundant. A
-- connection has NOT set `milexium.tenant_id` at the instant it is opened,
-- which is exactly when the version is read; under a policy that read would
-- return zero rows, zero rows is indistinguishable from "never stamped", and
-- the migration runner would conclude an already-migrated database needs
-- migrating. Deny-all is the right default for operator rows and the wrong
-- default for the record that says what shape those rows are in.

ALTER TABLE feature_values ENABLE ROW LEVEL SECURITY;
ALTER TABLE feature_values FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON feature_values;
CREATE POLICY tenant_isolation ON feature_values
    USING (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));

-- THE LEAKAGE GUARANTEE COMPOSES WITH THIS POLICY, it is not weakened by it.
-- ADR-0041's load-bearing invariant is that an as-of read at label time t returns
-- only values whose knowledge_time is STRICTLY < t, enforced as a SQL predicate
-- (`knowledge_time < ?`) over fixed-width canonical ISO-8601 UTC text. The policy
-- above is an ADDITIONAL conjunct on the same scan's qualification, never a
-- substitute for it: the rows returned are the INTERSECTION of "my tenant's" and
-- "strictly in the past". Neither predicate can rescue a row the other excludes,
-- which is why the test suite proves the crossing case explicitly -- a read of
-- another tenant's series at a timestamp that would happily admit the value
-- returns nothing at all.

ALTER TABLE promotion_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE promotion_decisions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON promotion_decisions;
CREATE POLICY tenant_isolation ON promotion_decisions
    USING (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));

ALTER TABLE promotion_rollbacks ENABLE ROW LEVEL SECURITY;
ALTER TABLE promotion_rollbacks FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON promotion_rollbacks;
CREATE POLICY tenant_isolation ON promotion_rollbacks
    USING (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));

-- The three MUTABLE role tables. They matter as much as the two ledgers: the
-- champion pointer is what actually serves traffic, so a cross-tenant write here
-- would not merely leak history, it would change which model answers another
-- operator's requests.
ALTER TABLE promotion_champions ENABLE ROW LEVEL SECURITY;
ALTER TABLE promotion_champions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON promotion_champions;
CREATE POLICY tenant_isolation ON promotion_champions
    USING (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));

ALTER TABLE promotion_champion_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE promotion_champion_history FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON promotion_champion_history;
CREATE POLICY tenant_isolation ON promotion_champion_history
    USING (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));

ALTER TABLE promotion_challengers ENABLE ROW LEVEL SECURITY;
ALTER TABLE promotion_challengers FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON promotion_challengers;
CREATE POLICY tenant_isolation ON promotion_challengers
    USING (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));

ALTER TABLE promotion_canaries ENABLE ROW LEVEL SECURITY;
ALTER TABLE promotion_canaries FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON promotion_canaries;
CREATE POLICY tenant_isolation ON promotion_canaries
    USING (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));
