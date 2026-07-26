-- HISTORICAL ARTIFACT -- schema version 2, the ADR-0048 (MX-D-TENANT-ISOLATION-006)
-- shape of the Program D tables, BEFORE the persistent model catalog.
--
-- THIS FILE IS THE SPECIFICATION OF WHAT SCHEMA VERSION 2 IS, and -- unlike its
-- version-1 sibling -- IT IS ALSO APPLIED, by exactly one caller: the 1 -> 2
-- migration in app/core/migrations.py. That is deliberate and it is the
-- property that makes an ordered chain actually ordered.
--
-- WHY THE 1 -> 2 STEP MUST NOT APPLY THE *CURRENT* DDL. It used to, because
-- while versions 2 and CURRENT were the same thing there was no difference to
-- observe. They are not the same thing any more. A 1 -> 2 step that created the
-- current shape would leave a database whose TABLES are at version 3 while its
-- ledger says 2, for the window between the two stamps -- and a crash in that
-- window (or a SQLite process killed between commits) leaves a database that the
-- next open REFUSES with SchemaShapeMismatchError, naming a contradiction nobody
-- introduced by hand. Each step now produces exactly its own version's shape, so
-- an interrupted chain always resumes from a state that is internally consistent.
--
-- evidence/conformance/property-tests/test_core_migrations.py also builds genuine
-- version-2 databases from THIS FILE'S OWN BYTES, for the same reason it builds
-- version-1 ones from the pre-tenant file: a hand-written approximation in a test
-- would be free to drift from what ADR-0048 actually shipped.
--
-- The statements below are verbatim from `core_v0_1.sql` as of git 939b431 (the
-- MX-D-MIGRATIONS-008 tranche). Only this header is new. Note what is absent:
-- no `core_model_versions` and no `core_model_champions`, which is why a restart
-- lost the model catalog while the promotion roles survived -- the defect
-- MX-D-REGISTRY-PERSISTENCE-009 closes.

-- Append-only point-in-time feature values. A correction is a NEW row with a
-- later (or equal) knowledge_time, never an UPDATE: there is no UPDATE or
-- DELETE against this table anywhere in app/core, on purpose, exactly as
-- for the canonical decision_events ledger.
--
-- `knowledge_time` is when the value BECAME KNOWN. An as-of read at label time
-- t admits a row only when knowledge_time < t, strictly. `write_sequence` is
-- the per-(tenant, entity, feature) append order and breaks ties at an identical
-- knowledge_time in favour of the last write (a correction recorded at the same
-- instant supersedes what it corrects -- the canonical "latest recorded version
-- wins" rule).
CREATE TABLE IF NOT EXISTS feature_values (
    tenant_id       TEXT NOT NULL,
    entity_id       TEXT NOT NULL,
    feature_name    TEXT NOT NULL,
    value           DOUBLE PRECISION NOT NULL,
    knowledge_time  TEXT NOT NULL,
    write_sequence  INTEGER NOT NULL CHECK (write_sequence >= 1),
    PRIMARY KEY (tenant_id, entity_id, feature_name, write_sequence)
);

-- The as-of read's access path: tenant, then (entity, feature), then time, then
-- append order -- exactly the ORDER BY the strict-past query uses, with the
-- tenant predicate leading. One index serves BOTH the tenant boundary and the
-- leakage predicate, so adding tenant scoping does not turn `knowledge_time < t`
-- into a post-scan filter.
CREATE INDEX IF NOT EXISTS ix_feature_values_as_of
    ON feature_values (tenant_id, entity_id, feature_name, knowledge_time, write_sequence);

-- The promotion ledger: every evaluated gate, promoted or not. Append-only and
-- ordered WITHIN A TENANT by `decision_sequence` -- it is an audit trail, so a
-- rejected challenger is recorded just as durably as a promoted one, and "what
-- was decided, in what order" is answerable after a restart.
--
-- `decision_sequence` was the whole primary key before tenant isolation; it is
-- now `(tenant_id, decision_sequence)` for the reason stated in note (c) at the
-- top of this file -- under RLS the MAX() that assigns it can only see the
-- acting tenant's rows, so the counter is necessarily per-tenant.
CREATE TABLE IF NOT EXISTS promotion_decisions (
    tenant_id          TEXT NOT NULL,
    decision_sequence  INTEGER NOT NULL CHECK (decision_sequence >= 1),
    task               TEXT NOT NULL,
    challenger_id      TEXT NOT NULL,
    incumbent_id       TEXT,
    metric_name        TEXT NOT NULL,
    challenger_metric  DOUBLE PRECISION NOT NULL,
    incumbent_metric   DOUBLE PRECISION,
    higher_is_better   INTEGER NOT NULL CHECK (higher_is_better IN (0, 1)),
    min_improvement    DOUBLE PRECISION NOT NULL CHECK (min_improvement >= 0),
    margin             DOUBLE PRECISION,
    promoted           INTEGER NOT NULL CHECK (promoted IN (0, 1)),
    decided_at         TEXT NOT NULL,
    rationale          TEXT NOT NULL,
    PRIMARY KEY (tenant_id, decision_sequence)
);

-- Recorded demotions of the serving champion back to a prior one.
CREATE TABLE IF NOT EXISTS promotion_rollbacks (
    tenant_id          TEXT NOT NULL,
    rollback_sequence  INTEGER NOT NULL CHECK (rollback_sequence >= 1),
    task               TEXT NOT NULL,
    from_champion_id   TEXT NOT NULL,
    to_champion_id     TEXT NOT NULL,
    decided_at         TEXT NOT NULL,
    reason             TEXT NOT NULL,
    PRIMARY KEY (tenant_id, rollback_sequence)
);

-- Current serving roles. Unlike the two ledgers above these are MUTABLE
-- pointers (one champion per task, at most one canary per task): the ledger is
-- the history, these tables are the present. Every mutation of them is
-- accompanied by a ledger row.
-- One champion per (tenant, task): the primary key is what makes "a task has one
-- champion" true per operator rather than across all of them. Two tenants
-- running the same task name -- which is the normal case, `forecast.demand` is
-- not a customer-specific string -- each keep their own champion.
CREATE TABLE IF NOT EXISTS promotion_champions (
    tenant_id    TEXT NOT NULL,
    task         TEXT NOT NULL,
    champion_id  TEXT NOT NULL,
    PRIMARY KEY (tenant_id, task)
);

-- The rollback stack: prior champions for a task, most recent = highest
-- stack_position. `rollback` pops the top entry.
CREATE TABLE IF NOT EXISTS promotion_champion_history (
    tenant_id       TEXT NOT NULL,
    task            TEXT NOT NULL,
    stack_position  INTEGER NOT NULL CHECK (stack_position >= 1),
    champion_id     TEXT NOT NULL,
    PRIMARY KEY (tenant_id, task, stack_position)
);

-- The challenger pool. PRIMARY KEY (tenant_id, task, model_version_id) makes
-- enrolling the same version twice a no-op at the database layer, not merely in
-- application code; `enrol_sequence` preserves enrolment order for reads.
CREATE TABLE IF NOT EXISTS promotion_challengers (
    tenant_id         TEXT NOT NULL,
    task              TEXT NOT NULL,
    model_version_id  TEXT NOT NULL,
    enrol_sequence    INTEGER NOT NULL CHECK (enrol_sequence >= 1),
    PRIMARY KEY (tenant_id, task, model_version_id)
);

-- At most one canary per (tenant, task). The CHECK restates the controller's
-- [0, 1) rule at the database layer: a fraction of 1 would just be the champion,
-- so it can never be stored, even by a caller that bypassed the Python
-- validation.
CREATE TABLE IF NOT EXISTS promotion_canaries (
    tenant_id         TEXT NOT NULL,
    task              TEXT NOT NULL,
    model_version_id  TEXT NOT NULL,
    traffic_fraction  DOUBLE PRECISION NOT NULL
        CHECK (traffic_fraction >= 0 AND traffic_fraction < 1),
    PRIMARY KEY (tenant_id, task)
);
