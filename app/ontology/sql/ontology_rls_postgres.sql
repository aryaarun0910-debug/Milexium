-- PostgreSQL row-level security for the ontology, keyed on the SAME session GUC
-- (`milexium.tenant_id`) that app/canonical/sql/rls_postgres.sql and
-- app/core/sql/core_rls_postgres.sql already use.
--
-- ONE GUC NAME ACROSS ALL THREE PACKAGES IS DELIBERATE. A connection carrying
-- the canonical, core and ontology contracts at once cannot then be scoped to
-- two different tenants in two different packages -- which a second GUC name
-- would have made not merely possible but likely, since each package sets its
-- own before every operation.
--
-- ENABLE **AND** FORCE, on every table. `milexium_dev` OWNS these tables
-- (ADR-0006) and a table owner BYPASSES row-level security by default, so
-- ENABLE alone would leave every isolation test passing for the wrong reason --
-- a false green of exactly the kind this repository keeps finding. FORCE makes
-- the owner subject to the policy too. `milexium_dev` is not a superuser and
-- does not hold BYPASSRLS, and cannot grant itself either without one, so FORCE
-- is genuinely load-bearing. The conformance suite proves it by LIFTING force
-- and showing the boundary collapse, then restoring it.
--
-- DENY BY DEFAULT, INCLUDING THE CASE THAT ACTUALLY OCCURS.
-- `current_setting('milexium.tenant_id', true)` returns SQL NULL only when the
-- GUC was NEVER set in this session. After a RESET -- a pooled connection handed
-- back and reused, which is the case that happens in production -- it returns
-- the EMPTY STRING. `tenant_id = ''` is false for any real UUID, so these
-- policies deny in both cases; that is incidental to the id format rather than
-- guaranteed by it, so the conformance suite asserts the GUC reads as '' FIRST
-- and then that zero rows come back, rather than silently proving the NULL
-- branch and reporting it as the RESET case.
--
-- THE POLICIES ARE SYMMETRIC (read what you may write) on every table. There is
-- no platform-tenant read exemption of the kind model_versions carries in
-- app/canonical: nothing in the ontology is public. A decision episode is
-- one operator's dispatch history, their crew's shift pattern, and their
-- riders' pseudonymous trip records -- there is no version of it another tenant
-- has any business reading.

ALTER TABLE ontology_receipt_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE ontology_receipt_log FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON ontology_receipt_log;
CREATE POLICY tenant_isolation ON ontology_receipt_log
    USING      (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));

ALTER TABLE ontology_objects ENABLE ROW LEVEL SECURITY;
ALTER TABLE ontology_objects FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON ontology_objects;
CREATE POLICY tenant_isolation ON ontology_objects
    USING      (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));

ALTER TABLE ontology_relationships ENABLE ROW LEVEL SECURITY;
ALTER TABLE ontology_relationships FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON ontology_relationships;
CREATE POLICY tenant_isolation ON ontology_relationships
    USING      (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));

ALTER TABLE ontology_facts ENABLE ROW LEVEL SECURITY;
ALTER TABLE ontology_facts FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON ontology_facts;
CREATE POLICY tenant_isolation ON ontology_facts
    USING      (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));

ALTER TABLE ontology_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE ontology_events FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON ontology_events;
CREATE POLICY tenant_isolation ON ontology_events
    USING      (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));

ALTER TABLE ontology_identity_resolutions ENABLE ROW LEVEL SECURITY;
ALTER TABLE ontology_identity_resolutions FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON ontology_identity_resolutions;
CREATE POLICY tenant_isolation ON ontology_identity_resolutions
    USING      (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));

ALTER TABLE ontology_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE ontology_snapshots FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON ontology_snapshots;
CREATE POLICY tenant_isolation ON ontology_snapshots
    USING      (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));

ALTER TABLE ontology_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE ontology_actions FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON ontology_actions;
CREATE POLICY tenant_isolation ON ontology_actions
    USING      (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));

ALTER TABLE ontology_action_outcomes ENABLE ROW LEVEL SECURITY;
ALTER TABLE ontology_action_outcomes FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON ontology_action_outcomes;
CREATE POLICY tenant_isolation ON ontology_action_outcomes
    USING      (tenant_id = current_setting('milexium.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('milexium.tenant_id', true));
