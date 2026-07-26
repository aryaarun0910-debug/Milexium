-- PRIVILEGED, ONCE PER POSTGRESQL CLUSTER. Run as a superuser.
-- MX-A-LIFECYCLE-IMMUTABILITY-012.
--
-- WHY IT LIVES HERE RATHER THAN IN app/canonical/sql/ WITH THE REST OF THE
-- SCHEMA. Everything in app/canonical/sql is applied at runtime by an
-- UNPRIVILEGED store; this file cannot be, because it creates a role. ADR-0052
-- already established platform/infra/compose/initdb as the home for privileged
-- provisioning, and the postgres image runs every *.sql here, in lexical order, on
-- first init of an empty data directory -- so 01-app-role.sh has created
-- milexium_app before this file grants membership in it. One authoritative copy:
-- a second one under app/ would be free to drift from the one that actually
-- runs.
--
-- On an EXISTING volume this does NOT run (the same caveat ADR-0052 records), and
-- the natively-installed PostgreSQL 17 on port 5432 (ADR-0006) has no initdb hook
-- at all. Both need it applied by hand, once:
--
--   psql -U postgres -d milexium_dev -f platform/infra/compose/initdb/02-lifecycle-ledger-bootstrap.sql
--
-- Until that happens, PostgresCanonicalStore falls back to
-- app/canonical/sql/lifecycle_immutability_postgres.sql, reports
-- `lifecycle_immutability == "trigger_only"`, and the conformance suite refuses to
-- treat that as the sealed configuration.
--
-- ==========================================================================
-- WHY A PRIVILEGED STEP EXISTS AT ALL
-- ==========================================================================
-- ADR-0063's own commit message argued that "a guard living only in the
-- application is a guard a future direct-SQL path walks around" -- and then left
-- the lifecycle table's append-only property as exactly that: a convention held up
-- by the absence of an UPDATE statement in app/canonical. An external audit
-- wrote a valid denial, issued a direct SQL UPDATE changing actor_id, committed,
-- and read the forged actor back through the normal API with nothing reported.
--
-- A trigger alone does not fix that, and this is the crux: a table's OWNER can
-- `ALTER TABLE ... DISABLE TRIGGER`, `DROP TRIGGER`, or `CREATE OR REPLACE` the
-- function the trigger calls. If the application credential owns the table, an
-- immutability trigger is a speed bump it can remove in one statement. The guard
-- has to be owned by somebody the application cannot become -- which requires
-- creating a role, which requires privilege the application deliberately does not
-- have (ADR-0006/0052: milexium_dev and milexium_app are NOSUPERUSER, NOBYPASSRLS,
-- NOCREATEROLE). Hence: one privileged bootstrap, then unprivileged runtime.
--
-- ==========================================================================
-- THE MEMBERSHIP DIRECTION, WHICH IS THE WHOLE SECURITY ARGUMENT
-- ==========================================================================
-- `milexium_ledger_owner` is granted membership IN the application roles, never
-- the other way round. Role membership is not symmetric: the ledger owner can act
-- as the application (which is how it reaches a table the application created in a
-- schema the application owns), and the application CANNOT act as the ledger owner.
-- `pg_has_role('milexium_app', 'milexium_ledger_owner', 'USAGE')` must be FALSE,
-- and the conformance suite asserts exactly that before drawing any conclusion
-- from an immutability test.
--
-- The ledger owner is NOLOGIN: it is not a connection identity, only the owner of
-- the table and of the SECURITY DEFINER function below. It holds no superuser and
-- no BYPASSRLS, so FORCE ROW LEVEL SECURITY still binds it and the tenant policy
-- still applies to the table it owns.

-- --------------------------------------------------------------------------
-- 1. The role that owns the ledger.
-- --------------------------------------------------------------------------
-- Race-safe rather than check-then-create, matching the pattern
-- PostgisObservationStore uses for milexium_rls: two bootstraps starting together
-- would both see the role missing.
DO $bootstrap$
BEGIN
    CREATE ROLE milexium_ledger_owner
        NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
EXCEPTION WHEN duplicate_object THEN
    -- Re-assert the security-relevant attributes: a role created by hand in an
    -- earlier session must not silently retain privileges this one relies on being
    -- absent. Same stance as platform/infra/compose/initdb/01-app-role.sh.
    ALTER ROLE milexium_ledger_owner
        NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
END
$bootstrap$;

-- --------------------------------------------------------------------------
-- 2. Membership in each application role that exists on this cluster.
-- --------------------------------------------------------------------------
-- `ALTER TABLE ... OWNER TO` requires the executing role both to OWN the table
-- (i.e. to be a member of its current owner) and to be able to SET ROLE to the new
-- owner. The seal function runs as milexium_ledger_owner, so it needs membership
-- in whichever role created the table. Only roles that actually exist are granted,
-- so this file runs unchanged on the native instance (milexium_dev), on the
-- container (milexium_app), and on a cluster with both.
DO $bootstrap$
DECLARE
    application_role text;
BEGIN
    FOREACH application_role IN ARRAY ARRAY['milexium_app', 'milexium_dev', 'milexium_rls']
    LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = application_role) THEN
            EXECUTE format('GRANT %I TO milexium_ledger_owner', application_role);
        END IF;
    END LOOP;
END
$bootstrap$;

-- --------------------------------------------------------------------------
-- 3. The guard itself: refuse UPDATE, DELETE and TRUNCATE.
-- --------------------------------------------------------------------------
-- SQLSTATE MX001 rather than a message the conformance suite would have to match
-- on: a test that greps an error string passes for the wrong reason the moment the
-- wording changes, and fails for the wrong reason the moment an unrelated error
-- happens to contain the words. A custom SQLSTATE is checkable exactly.
CREATE OR REPLACE FUNCTION public.milexium_reject_lifecycle_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $guard$
BEGIN
    RAISE EXCEPTION
        'request_state_transitions is append-only: % is refused. A correction is a '
        'further transition, never an edit to or a removal of a recorded one.', TG_OP
        USING ERRCODE = 'MX001';
END
$guard$;
ALTER FUNCTION public.milexium_reject_lifecycle_mutation() OWNER TO milexium_ledger_owner;

-- --------------------------------------------------------------------------
-- 4. Transaction time, bounded by this server's own clock.
-- --------------------------------------------------------------------------
-- The audit's finding was that `recorded_at` was a CALLER argument, so the
-- "bitemporal" record proved only that two caller assertions were ordered. The
-- writer now stamps it -- but a DEFAULT alone would NOT have closed the finding,
-- because a DEFAULT only fires when the column is OMITTED and the audit's insert
-- supplied it explicitly. This trigger bounds whatever value arrives, from any
-- path including raw SQL, against clock_timestamp(). 60s is
-- RECORDED_AT_TOLERANCE_SECONDS in lifecycle.py; a conformance test pins the two.
--
-- The NULL branch is reachable: BEFORE INSERT triggers run ahead of NOT NULL
-- checking, so an explicit `recorded_at = NULL` arrives here and gets the server's
-- clock rather than an integrity error -- which is the "the database stamps it"
-- half of the requirement.
CREATE OR REPLACE FUNCTION public.milexium_bound_lifecycle_recorded_at()
RETURNS trigger
LANGUAGE plpgsql
AS $clock$
DECLARE
    skew_seconds double precision;
BEGIN
    IF NEW.recorded_at IS NULL THEN
        NEW.recorded_at := to_char(
            clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"+00:00"'
        );
    END IF;
    skew_seconds := abs(extract(epoch from (NEW.recorded_at::timestamptz - clock_timestamp())));
    IF skew_seconds > 60 THEN
        RAISE EXCEPTION
            'recorded_at % is % seconds from this server''s clock: it is not the '
            'transaction time. recorded_at is stamped by the writer and bounded '
            'here; it is not a value any caller may assert.',
            NEW.recorded_at, round(skew_seconds)::text
            USING ERRCODE = 'MX002';
    END IF;
    RETURN NEW;
END
$clock$;
ALTER FUNCTION public.milexium_bound_lifecycle_recorded_at() OWNER TO milexium_ledger_owner;

-- --------------------------------------------------------------------------
-- 5. The seal: applied per schema, by the unprivileged application role.
-- --------------------------------------------------------------------------
-- SECURITY DEFINER, owned by milexium_ledger_owner, so calling it is the one
-- capability an application role has that it could not perform directly. What it
-- can do is bounded by what the ledger owner can do, and the ledger owner's rights
-- are exactly: the union of the application roles' rights (by membership), plus
-- being itself. It cannot create roles, cannot bypass RLS, and is not a superuser.
--
-- `SET search_path` is not decoration on a SECURITY DEFINER function: without it a
-- caller could put a malicious `format` or `pg_class` on the path and have this
-- body resolve to it while running as the owner.
--
-- The order matters and is not arbitrary:
--   1. drop any triggers the APPLICATION installed (the unprivileged fallback
--      installs its own, and their function is application-owned, therefore
--      application-rewritable -- they must not survive the seal);
--   2. transfer ownership;
--   3. install the guards from the ledger-owned functions in public;
--   4. reduce the application to INSERT + SELECT.
-- Doing (4) before (2) would be self-defeating -- the application would still own
-- the table and could simply GRANT itself back.
CREATE OR REPLACE FUNCTION public.milexium_seal_lifecycle_ledger(target_schema text)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $seal$
DECLARE
    table_owner text;
    qualified   text := format('%I.%I', target_schema, 'request_state_transitions');
BEGIN
    SELECT pg_get_userbyid(c.relowner) INTO table_owner
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = target_schema
       AND c.relname = 'request_state_transitions';

    IF table_owner IS NULL THEN
        RAISE EXCEPTION 'no request_state_transitions table in schema %', target_schema
            USING ERRCODE = 'MX003';
    END IF;

    IF table_owner = 'milexium_ledger_owner' THEN
        RETURN 'already_sealed';
    END IF;

    EXECUTE format('DROP TRIGGER IF EXISTS milexium_lifecycle_reject_update ON %s', qualified);
    EXECUTE format('DROP TRIGGER IF EXISTS milexium_lifecycle_reject_delete ON %s', qualified);
    EXECUTE format('DROP TRIGGER IF EXISTS milexium_lifecycle_reject_truncate ON %s', qualified);
    EXECUTE format('DROP TRIGGER IF EXISTS milexium_lifecycle_bound_recorded_at ON %s', qualified);
    EXECUTE format('DROP FUNCTION IF EXISTS %I.milexium_reject_lifecycle_mutation()', target_schema);
    EXECUTE format('DROP FUNCTION IF EXISTS %I.milexium_bound_lifecycle_recorded_at()', target_schema);

    EXECUTE format('ALTER TABLE %s OWNER TO milexium_ledger_owner', qualified);

    EXECUTE format(
        'ALTER TABLE %s ALTER COLUMN recorded_at SET DEFAULT '
        'to_char(clock_timestamp() AT TIME ZONE ''UTC'', ''YYYY-MM-DD"T"HH24:MI:SS.US"+00:00"'')',
        qualified
    );

    EXECUTE format(
        'CREATE TRIGGER milexium_lifecycle_reject_update BEFORE UPDATE ON %s '
        'FOR EACH ROW EXECUTE FUNCTION public.milexium_reject_lifecycle_mutation()', qualified);
    EXECUTE format(
        'CREATE TRIGGER milexium_lifecycle_reject_delete BEFORE DELETE ON %s '
        'FOR EACH ROW EXECUTE FUNCTION public.milexium_reject_lifecycle_mutation()', qualified);
    -- TRUNCATE fires no row-level trigger, so it needs a statement-level one of its
    -- own. TRUNCATE is also not granted to the application below -- but "not
    -- granted" and "refused" are different claims, and this table should not rely
    -- on a privilege matrix nobody re-reads.
    EXECUTE format(
        'CREATE TRIGGER milexium_lifecycle_reject_truncate BEFORE TRUNCATE ON %s '
        'FOR EACH STATEMENT EXECUTE FUNCTION public.milexium_reject_lifecycle_mutation()', qualified);
    EXECUTE format(
        'CREATE TRIGGER milexium_lifecycle_bound_recorded_at BEFORE INSERT ON %s '
        'FOR EACH ROW EXECUTE FUNCTION public.milexium_bound_lifecycle_recorded_at()', qualified);

    EXECUTE format('REVOKE ALL ON TABLE %s FROM PUBLIC', qualified);
    EXECUTE format('REVOKE ALL ON TABLE %s FROM %I', qualified, table_owner);
    EXECUTE format('GRANT INSERT, SELECT ON TABLE %s TO %I', qualified, table_owner);

    RETURN 'owner_separated';
END
$seal$;
ALTER FUNCTION public.milexium_seal_lifecycle_ledger(text) OWNER TO milexium_ledger_owner;

-- Any role may seal a lifecycle table it created. That is not a privilege
-- escalation: the function's reach is the ledger owner's reach, which is the union
-- of the application roles' own rights, and its only effect is to REMOVE the
-- caller's ability to mutate a table it owned. A caller pointing it at another
-- schema can only affect a table it could already have altered itself.
GRANT EXECUTE ON FUNCTION public.milexium_seal_lifecycle_ledger(text) TO PUBLIC;

-- A read-only report of what is actually enforced on a given schema, so the
-- conformance suite and an operator can ask the DATABASE rather than trusting this
-- file to have run. Returns the table owner, whether each guard exists, and the
-- application role's privileges.
CREATE OR REPLACE FUNCTION public.milexium_lifecycle_ledger_status(target_schema text)
RETURNS TABLE (
    table_owner        text,
    trigger_count      bigint,
    recorded_at_default text
)
LANGUAGE sql
STABLE
AS $status$
    SELECT
        pg_get_userbyid(c.relowner),
        (SELECT count(*) FROM pg_trigger t
          WHERE t.tgrelid = c.oid AND NOT t.tgisinternal),
        pg_get_expr(d.adbin, d.adrelid)
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
      LEFT JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'recorded_at'
      LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
     WHERE n.nspname = target_schema
       AND c.relname = 'request_state_transitions';
$status$;
GRANT EXECUTE ON FUNCTION public.milexium_lifecycle_ledger_status(text) TO PUBLIC;
