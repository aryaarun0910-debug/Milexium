-- PostgreSQL row-level security (RLS) for tenant isolation, contract v0.1.
-- See architecture/decisions/0018-postgres-row-level-security-tenant-isolation.md
-- (and 0006-dedicated-postgres-dev-role.md, 0008-postgres-test-isolation-strategy.md).
--
-- WHY THIS FILE IS SEPARATE FROM schema_v0_1.sql
-- schema_v0_1.sql is the *portable* DDL: it must run unmodified on both SQLite
-- (the demo engine) and PostgreSQL 17 (the production target), so it may not
-- contain any Postgres-only construct. RLS is Postgres-only, so it lives here
-- and is applied *only* by PostgresCanonicalStore, after the portable schema.
--
-- THE OWNER-BYPASS PROBLEM (the whole point of this file)
-- The application role `milexium_dev` OWNS the schema and every table in it
-- (ADR-0006). A table owner BYPASSES RLS by default -- so a naive
-- `ENABLE ROW LEVEL SECURITY` + policy would NOT constrain our own connections
-- and every isolation test would pass for the wrong reason (a false green).
-- `ALTER TABLE ... FORCE ROW LEVEL SECURITY` makes the owner subject to the
-- policy too. `milexium_dev` is not a superuser and does not hold BYPASSRLS
-- (ADR-0006), and it cannot grant itself either without a superuser, so FORCE
-- is genuinely load-bearing: with it, even the owning credential cannot read
-- across tenants; conformance/adversarial/test_postgres_rls_isolation.py proves
-- exactly this, including a test that lifts FORCE to show the boundary collapse.
--
-- THE SESSION KEY (a GUC, not an application WHERE-clause)
-- Every policy is keyed on the custom session setting `milexium.tenant_id`.
-- current_setting('milexium.tenant_id', true) reads it with missing_ok=true, so
-- an UNSET session yields SQL NULL and `tenant_id = NULL` is never true: the
-- default is DENY-ALL, not allow-all. PostgresCanonicalStore sets this GUC per
-- operation (session scope) to the tenant it is acting for, via
-- `set_config('milexium.tenant_id', <tenant>, false)`, before any read or write.
-- The USING clause governs which existing rows are visible (SELECT/UPDATE/
-- DELETE); the WITH CHECK clause governs which new/updated rows are permitted
-- (INSERT/UPDATE), so a session acting as tenant B cannot even write a row
-- stamped with tenant A's id.
--
-- Referential-integrity checks (the FK from each child table to tenants) always
-- bypass RLS in PostgreSQL by design, so these policies do not break inserts
-- into tenant-scoped tables whose parent `tenants` row is not "visible" under
-- the acting GUC -- confirmed against PostgreSQL 17.

-- tenants is the boundary table: its own primary key IS the tenant id, so it is
-- scoped to itself. A session may see/insert only the tenant row matching its
-- GUC. Listing all tenants is a platform-admin operation that legitimately
-- requires a dedicated BYPASSRLS role (not the application role) -- deliberately
-- out of reach of milexium_dev, and out of scope for v0.1.
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenants FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON tenants
    USING (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));

ALTER TABLE service_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE service_requests FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON service_requests
    USING (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));

ALTER TABLE vehicles ENABLE ROW LEVEL SECURITY;
ALTER TABLE vehicles FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON vehicles
    USING (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));

ALTER TABLE drivers ENABLE ROW LEVEL SECURITY;
ALTER TABLE drivers FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON drivers
    USING (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));

ALTER TABLE policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE policies FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON policies
    USING (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));

-- model_versions and forecast_vintages both carry tenant_id, so they are covered
-- for completeness -- "database-layer tenant isolation" with an unguarded
-- tenant-scoped table is exactly the false assurance this packet exists to
-- prevent. NOTE: ModelVersion.tenant_id has an unresolved meaning for
-- platform-trained models that belong to no single customer (ADR-0010); a strict
-- `tenant_id = GUC` policy is correct here only once a "platform tenant"
-- convention is chosen. No store method reads/writes these tables yet, so this
-- guards them without prescribing that convention.
ALTER TABLE model_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_versions FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON model_versions
    USING (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));

ALTER TABLE forecast_vintages ENABLE ROW LEVEL SECURITY;
ALTER TABLE forecast_vintages FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON forecast_vintages
    USING (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));

ALTER TABLE schedule_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE schedule_runs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON schedule_runs
    USING (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));

-- decision_alternatives has no tenant_id column of its own -- it is tenant-scoped
-- transitively through schedule_runs(schedule_run_id). Its policy therefore keys
-- on the parent run's tenant. The subquery is itself evaluated under the acting
-- GUC, so it naturally sees only the current tenant's runs.
ALTER TABLE decision_alternatives ENABLE ROW LEVEL SECURITY;
ALTER TABLE decision_alternatives FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON decision_alternatives
    USING (schedule_run_id IN (
        SELECT schedule_run_id FROM schedule_runs
        WHERE tenant_id = current_setting('milexium.tenant_id', true)))
    WITH CHECK (schedule_run_id IN (
        SELECT schedule_run_id FROM schedule_runs
        WHERE tenant_id = current_setting('milexium.tenant_id', true)));

ALTER TABLE decision_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE decision_events FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON decision_events
    USING (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));

ALTER TABLE outcomes ENABLE ROW LEVEL SECURITY;
ALTER TABLE outcomes FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON outcomes
    USING (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));

ALTER TABLE outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE outbox FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON outbox
    USING (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));

-- The request-INDEPENDENT operational observation tables (ADR-0031/0035). Both
-- carry tenant_id directly, so they take the plain policy -- but they were added
-- to schema_v0_1.sql AFTER this file was written and so sat here unguarded: a
-- tenant-scoped table with no policy is precisely the false assurance ADR-0018
-- exists to prevent, and vehicle position/occupancy is the most sensitive
-- operational data in the schema (SensitivityClass.PRECISE_LOCATION).
--
-- ENABLE *and* FORCE for the reason stated at the top of this file: milexium_dev
-- OWNS these tables, so ENABLE alone would leave the owning credential
-- unconstrained and every isolation test would pass for the wrong reason.
--
-- SCOPE NOTE: this file is applied by PostgresCanonicalStore (the native
-- PostgreSQL 17 on 5432) only. PostgisObservationStore targets the containerized
-- PostGIS on 5433 and applies the portable schema plus postgis_postgres.sql, not
-- this file -- its reads are tenant-filtered in SQL but not policy-enforced.
-- Extending RLS to that container store is a separate decision (it would require
-- the store to set the GUC per operation) and is deliberately NOT assumed here.
ALTER TABLE vehicle_observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE vehicle_observations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON vehicle_observations
    USING (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));

ALTER TABLE stop_time_observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE stop_time_observations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON stop_time_observations
    USING (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));
