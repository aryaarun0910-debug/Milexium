-- PostgreSQL half of the ontology's two structural invariants.
-- Applied by OntologyStore AFTER the portable DDL and re-appliable, because
-- reopening a named schema runs it again.
--
-- Same two invariants as ontology_immutability_sqlite.sql, in PL/pgSQL:
--   MX001  append-only: UPDATE, DELETE and TRUNCATE are refused on every table
--   MX002  receipt monotonicity: no row may arrive before the tenant's maximum
--   MX003  receipt sequence gaplessness
--
-- WHY TRUNCATE IS LISTED SEPARATELY. A statement-level TRUNCATE trigger is the
-- only thing that catches it: TRUNCATE fires no row-level trigger, so a table
-- guarded only by BEFORE UPDATE/DELETE can be emptied in one statement while
-- every test that only tried UPDATE stays green. That is precisely the shape of
-- false green this repository has been finding, so it is closed here rather
-- than noted as a to-do.
--
-- ===========================================================================
-- WHAT THIS DOES **NOT** BUY, AND WHY IT IS SAID HERE RATHER THAN OMITTED
-- ===========================================================================
-- The application role owns these tables. A table owner may DROP or DISABLE a
-- trigger, so on its own this is a database-enforced convention rather than a
-- privilege boundary: it stops every accidental and casual mutation and stops
-- none of a determined holder of the application credential.
--
-- The complete repair needs THREE layers and this file is the second:
--   1. PRIVILEGE. The tables must be owned by a role no application credential
--      can assume, with the application role holding INSERT and SELECT only:
--
--        CREATE ROLE milexium_ledger_owner NOLOGIN;
--        ALTER TABLE ontology_facts OWNER TO milexium_ledger_owner;   -- x9
--        REVOKE UPDATE, DELETE, TRUNCATE ON ontology_facts FROM milexium_dev;
--        GRANT  INSERT, SELECT ON ontology_facts TO milexium_dev;
--
--      Creating a role requires a superuser, which `milexium_dev` deliberately
--      is not (ADR-0006), so this packet CANNOT install it and does not pretend
--      to. It is a deployment step, written out above so it is a task rather
--      than a discovery.
--   2. THESE TRIGGERS.
--   3. DETECTION. ontology_receipt_log is hash-chained, so a mutation that got
--      past 1 and 2 -- a backup edited offline, a replica diverging, a restore
--      from a tampered dump -- is detectable on read by recomputing the chain.
--      This is tamper EVIDENCE, not authentication: there is no secret in the
--      hash, so a party who can write can also recompute. What it catches is a
--      row changed WITHOUT recomputation.
--
-- Layers 2 and 3 land in this packet. Layer 1 is named as a limitation.

CREATE OR REPLACE FUNCTION ontology_refuse_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'MX001 % is append-only: % refused. A correction is a new row with a later '
        'receipt time, never an edit', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'raise_exception';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION ontology_check_receipt_monotonic() RETURNS trigger AS $$
DECLARE
    max_time TEXT;
    max_seq  BIGINT;
BEGIN
    SELECT MAX(receipt_time), MAX(receipt_sequence) INTO max_time, max_seq
    FROM ontology_receipt_log WHERE tenant_id = NEW.tenant_id;

    IF max_time IS NOT NULL AND NEW.receipt_time < max_time THEN
        RAISE EXCEPTION
            'MX002 receipt time went backwards for tenant % (% < %): refusing to '
            'insert a row before an already-taken snapshot boundary',
            NEW.tenant_id, NEW.receipt_time, max_time
            USING ERRCODE = 'raise_exception';
    END IF;

    IF NEW.receipt_sequence <> COALESCE(max_seq, 0) + 1 THEN
        RAISE EXCEPTION
            'MX003 receipt sequence % is not the next in tenant %''s order (expected %)',
            NEW.receipt_sequence, NEW.tenant_id, COALESCE(max_seq, 0) + 1
            USING ERRCODE = 'raise_exception';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS ontology_receipt_log_monotonic ON ontology_receipt_log;
CREATE TRIGGER ontology_receipt_log_monotonic
    BEFORE INSERT ON ontology_receipt_log
    FOR EACH ROW EXECUTE FUNCTION ontology_check_receipt_monotonic();

DROP TRIGGER IF EXISTS ontology_receipt_log_immutable ON ontology_receipt_log;
CREATE TRIGGER ontology_receipt_log_immutable
    BEFORE UPDATE OR DELETE ON ontology_receipt_log
    FOR EACH ROW EXECUTE FUNCTION ontology_refuse_mutation();
DROP TRIGGER IF EXISTS ontology_receipt_log_no_truncate ON ontology_receipt_log;
CREATE TRIGGER ontology_receipt_log_no_truncate
    BEFORE TRUNCATE ON ontology_receipt_log
    FOR EACH STATEMENT EXECUTE FUNCTION ontology_refuse_mutation();

DROP TRIGGER IF EXISTS ontology_objects_immutable ON ontology_objects;
CREATE TRIGGER ontology_objects_immutable
    BEFORE UPDATE OR DELETE ON ontology_objects
    FOR EACH ROW EXECUTE FUNCTION ontology_refuse_mutation();
DROP TRIGGER IF EXISTS ontology_objects_no_truncate ON ontology_objects;
CREATE TRIGGER ontology_objects_no_truncate
    BEFORE TRUNCATE ON ontology_objects
    FOR EACH STATEMENT EXECUTE FUNCTION ontology_refuse_mutation();

DROP TRIGGER IF EXISTS ontology_relationships_immutable ON ontology_relationships;
CREATE TRIGGER ontology_relationships_immutable
    BEFORE UPDATE OR DELETE ON ontology_relationships
    FOR EACH ROW EXECUTE FUNCTION ontology_refuse_mutation();
DROP TRIGGER IF EXISTS ontology_relationships_no_truncate ON ontology_relationships;
CREATE TRIGGER ontology_relationships_no_truncate
    BEFORE TRUNCATE ON ontology_relationships
    FOR EACH STATEMENT EXECUTE FUNCTION ontology_refuse_mutation();

DROP TRIGGER IF EXISTS ontology_facts_immutable ON ontology_facts;
CREATE TRIGGER ontology_facts_immutable
    BEFORE UPDATE OR DELETE ON ontology_facts
    FOR EACH ROW EXECUTE FUNCTION ontology_refuse_mutation();
DROP TRIGGER IF EXISTS ontology_facts_no_truncate ON ontology_facts;
CREATE TRIGGER ontology_facts_no_truncate
    BEFORE TRUNCATE ON ontology_facts
    FOR EACH STATEMENT EXECUTE FUNCTION ontology_refuse_mutation();

DROP TRIGGER IF EXISTS ontology_events_immutable ON ontology_events;
CREATE TRIGGER ontology_events_immutable
    BEFORE UPDATE OR DELETE ON ontology_events
    FOR EACH ROW EXECUTE FUNCTION ontology_refuse_mutation();
DROP TRIGGER IF EXISTS ontology_events_no_truncate ON ontology_events;
CREATE TRIGGER ontology_events_no_truncate
    BEFORE TRUNCATE ON ontology_events
    FOR EACH STATEMENT EXECUTE FUNCTION ontology_refuse_mutation();

DROP TRIGGER IF EXISTS ontology_identity_immutable ON ontology_identity_resolutions;
CREATE TRIGGER ontology_identity_immutable
    BEFORE UPDATE OR DELETE ON ontology_identity_resolutions
    FOR EACH ROW EXECUTE FUNCTION ontology_refuse_mutation();
DROP TRIGGER IF EXISTS ontology_identity_no_truncate ON ontology_identity_resolutions;
CREATE TRIGGER ontology_identity_no_truncate
    BEFORE TRUNCATE ON ontology_identity_resolutions
    FOR EACH STATEMENT EXECUTE FUNCTION ontology_refuse_mutation();

DROP TRIGGER IF EXISTS ontology_snapshots_immutable ON ontology_snapshots;
CREATE TRIGGER ontology_snapshots_immutable
    BEFORE UPDATE OR DELETE ON ontology_snapshots
    FOR EACH ROW EXECUTE FUNCTION ontology_refuse_mutation();
DROP TRIGGER IF EXISTS ontology_snapshots_no_truncate ON ontology_snapshots;
CREATE TRIGGER ontology_snapshots_no_truncate
    BEFORE TRUNCATE ON ontology_snapshots
    FOR EACH STATEMENT EXECUTE FUNCTION ontology_refuse_mutation();

DROP TRIGGER IF EXISTS ontology_actions_immutable ON ontology_actions;
CREATE TRIGGER ontology_actions_immutable
    BEFORE UPDATE OR DELETE ON ontology_actions
    FOR EACH ROW EXECUTE FUNCTION ontology_refuse_mutation();
DROP TRIGGER IF EXISTS ontology_actions_no_truncate ON ontology_actions;
CREATE TRIGGER ontology_actions_no_truncate
    BEFORE TRUNCATE ON ontology_actions
    FOR EACH STATEMENT EXECUTE FUNCTION ontology_refuse_mutation();

DROP TRIGGER IF EXISTS ontology_outcomes_immutable ON ontology_action_outcomes;
CREATE TRIGGER ontology_outcomes_immutable
    BEFORE UPDATE OR DELETE ON ontology_action_outcomes
    FOR EACH ROW EXECUTE FUNCTION ontology_refuse_mutation();
DROP TRIGGER IF EXISTS ontology_outcomes_no_truncate ON ontology_action_outcomes;
CREATE TRIGGER ontology_outcomes_no_truncate
    BEFORE TRUNCATE ON ontology_action_outcomes
    FOR EACH STATEMENT EXECUTE FUNCTION ontology_refuse_mutation();
