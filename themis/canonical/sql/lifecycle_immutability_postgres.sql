-- UNPRIVILEGED FALLBACK for a cluster where the ledger bootstrap has not been run.
-- MX-A-LIFECYCLE-IMMUTABILITY-012.
--
-- WHAT THIS IS. talos/infra/compose/initdb/02-lifecycle-ledger-bootstrap.sql needs a superuser: it
-- creates the `milexium_ledger_owner` role that makes the immutability guard
-- something the application cannot remove. On a cluster where nobody has run it --
-- a fresh clone, a colleague's laptop, a CI service container -- the canonical
-- store still has to leave the lifecycle table better than mutable. This file is
-- what an ordinary, table-OWNING application role can install by itself.
--
-- WHAT IT IS WORTH, AND THIS IS THE POINT. The trigger below is created by, and
-- calls a function owned by, the role that OWNS the table. That role can
-- `DROP TRIGGER`, `ALTER TABLE ... DISABLE TRIGGER`, or `CREATE OR REPLACE` the
-- function into a no-op. So this stops an accidental UPDATE, a cleanup script, an
-- ORM upsert and a careless migration -- and it does NOT stop a determined holder
-- of the application credential. It is the "guard living only in the application"
-- shape one layer down, and calling it a boundary would be repeating the exact
-- mistake this packet exists to correct.
--
-- The store therefore records which of the two it got (`lifecycle_immutability`),
-- the sealed path is the DEFAULT and is what the deployment claim rests on, and
-- the conformance suite asserts the sealed properties rather than accepting
-- whichever level happens to be present.
--
-- Applied by PostgresCanonicalStore inside its own schema (search_path already
-- set), so the unqualified names below resolve there.

CREATE OR REPLACE FUNCTION milexium_reject_lifecycle_mutation()
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

CREATE OR REPLACE FUNCTION milexium_bound_lifecycle_recorded_at()
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

ALTER TABLE request_state_transitions
    ALTER COLUMN recorded_at SET DEFAULT
        to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"+00:00"');

CREATE TRIGGER milexium_lifecycle_reject_update
    BEFORE UPDATE ON request_state_transitions
    FOR EACH ROW EXECUTE FUNCTION milexium_reject_lifecycle_mutation();

CREATE TRIGGER milexium_lifecycle_reject_delete
    BEFORE DELETE ON request_state_transitions
    FOR EACH ROW EXECUTE FUNCTION milexium_reject_lifecycle_mutation();

CREATE TRIGGER milexium_lifecycle_reject_truncate
    BEFORE TRUNCATE ON request_state_transitions
    FOR EACH STATEMENT EXECUTE FUNCTION milexium_reject_lifecycle_mutation();

CREATE TRIGGER milexium_lifecycle_bound_recorded_at
    BEFORE INSERT ON request_state_transitions
    FOR EACH ROW EXECUTE FUNCTION milexium_bound_lifecycle_recorded_at();
