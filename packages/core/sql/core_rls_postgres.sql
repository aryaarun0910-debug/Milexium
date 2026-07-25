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
-- ONE POLICY BELOW IS ASYMMETRIC, AND IT IS NEW (MX-D-REGISTRY-PERSISTENCE-009).
-- Until schema version 3 this file could say "no asymmetric policy here": nothing
-- in Program D's runtime state was platform-owned, because a feature value and a
-- promotion decision belong to the operator whose data produced them. The model
-- CATALOG is the exception, and it is the exception for the reason ADR-0040
-- reserved a platform tenant in the first place -- the five models this
-- repository actually has evaluation evidence for are trained on public data
-- (NYC TLC, Chicago TNP, MTA, NTD) and belong to no customer.
-- `core_model_versions` therefore carries the SAME asymmetric policy
-- `model_versions` carries in packages/canonical/sql/rls_postgres.sql, including
-- ADR-0043's tightening, rather than a second design for the same rule. Every
-- other policy in this file stays symmetric: what you may read, you may write.
-- `USING` governs which existing rows are visible (SELECT/UPDATE/DELETE);
-- `WITH CHECK` governs which new rows are permitted (INSERT/UPDATE), so a session
-- acting as tenant B cannot even write a row stamped with tenant A's id.
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
-- THE HAZARD ADR-0055 NAMED, NOW FACED (MX-D-REGISTRY-PERSISTENCE-009). That
-- ordering saved the 1 -> 2 migration only because version 1 PREDATES this file
-- -- there were no policies to see through. From version 2 onward there are, and
-- ADR-0055 recorded the consequence in its limitations: "a 2 -> N migration that
-- counts or copies rows with no GUC in scope sees ZERO rows and 'succeeds'
-- having moved nothing". The 2 -> 3 migration counts rows, so it is the first to
-- meet this. It does NOT hope: `migrations._migrate_2_to_3` calls
-- `CoreDatabase.suspend_row_level_security()` (DISABLE on every table this file
-- guards, plus `SET LOCAL row_security = off` so PostgreSQL itself ERRORS rather
-- than filtering silently if anything was missed), then REFUSES with
-- `RowSecurityInForceError` if `pg_class.relrowsecurity` is still true for any
-- table it is about to read -- so a future edit that drops the suspension fails
-- loudly instead of recording a confident zero. It then re-applies this file
-- BEFORE its own transaction commits, so the window in which these tables are
-- unguarded is never committed and never visible to another session (and
-- `ALTER TABLE` holds ACCESS EXCLUSIVE throughout it anyway). A migration that
-- raises rolls that DISABLE back with everything else.
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

-- --------------------------------------------------------------------------
-- SCHEMA VERSION 3: THE MODEL CATALOG (MX-D-REGISTRY-PERSISTENCE-009)
--
-- THE ONE ASYMMETRIC POLICY IN THIS FILE. `core_model_versions` holds the
-- `ModelVersion` catalog, and ADR-0040's reserved `PLATFORM_TENANT_ID` names the
-- models that belong to no customer. Those have to be READABLE BY EVERY TENANT
-- AND WRITABLE BY NONE OF THEM: a strict `tenant_id = GUC` would make the
-- platform's own models invisible to the customers who must run them, which is
-- the entire reason the reserved tenant exists.
--
--   USING      admits the platform id  -> any SCOPED tenant may READ a platform model.
--   WITH CHECK OMITS the platform id   -> a session acting as a customer CANNOT
--                                         write a platform-stamped row.
--
-- This mirrors `packages/canonical/sql/rls_postgres.sql`'s `model_versions`
-- clause deliberately, character for character in the parts that matter, so an
-- in-memory resolution (`ModelRegistry._is_visible_to`), a canonical-store read
-- and a Program D read cannot disagree about what a tenant may see. The literal
-- below is the same value as `packages/canonical/ids.PLATFORM_TENANT_ID`;
-- conformance/property-tests/test_model_registry_persistence.py asserts the two
-- have not drifted apart, and proves the asymmetry adversarially.
--
-- THE EMPTY-STRING TRAP LIVES IN THIS CLAUSE AND NOWHERE ELSE IN THIS FILE
-- (ADR-0043). Every other policy here survives a RESET session only INCIDENTALLY,
-- because `tenant_id = ''` is false for any real UUIDv7. The platform branch has
-- no such accident protecting it: `tenant_id = '<PLATFORM>'` is true regardless
-- of the GUC, so without the second conjunct an UNSET or RESET session would read
-- every platform model and this file's advertised deny-all default would be false
-- for the one table that has rows nobody owns. `current_setting(name, true)`
-- returns NULL only when the GUC was NEVER set; after `RESET` (or `SET x = ''`)
-- it returns the EMPTY STRING, which an `IS NOT NULL` guard happily accepts -- a
-- fix written that way does NOT work and cost ADR-0043 a failed attempt. So the
-- test is `coalesce(..., '') <> ''`, explicitly, and no guard in this file is
-- written as `IS NOT NULL`.
--
-- HONEST LIMIT, the same one ADR-0043 records: the GUC *is* the identity, so a
-- session that sets `milexium.tenant_id` to the platform id IS acting as the
-- platform and may write platform rows -- that is how the platform seeds its own
-- catalog. What is proved impossible is a session acting as a CUSTOMER forging
-- one.
ALTER TABLE core_model_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE core_model_versions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON core_model_versions;
CREATE POLICY tenant_isolation ON core_model_versions
    USING (tenant_id = current_setting('milexium.tenant_id', true)
           OR (tenant_id = '00000000-0000-7000-8000-000000000000'
               AND coalesce(current_setting('milexium.tenant_id', true), '') <> ''))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));

-- AND THE REGISTRY'S CHAMPION POINTER IS SYMMETRIC, deliberately, even though it
-- points AT rows that may be platform-owned. Which model an operator has chosen
-- to serve is that operator's decision and nobody else's business -- there is no
-- such thing as a platform-owned champion pointer, and admitting the platform id
-- here would have let one tenant read (and, without the asymmetry, write) another
-- operator's serving choice. A platform MODEL is shared; the CHOICE to run it is
-- not.
ALTER TABLE core_model_champions ENABLE ROW LEVEL SECURITY;
ALTER TABLE core_model_champions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON core_model_champions;
CREATE POLICY tenant_isolation ON core_model_champions
    USING (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));
