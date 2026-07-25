-- Program D (Core / adaptive memory) schema, contract version 0.1.0.
-- See architecture/decisions/0034-adaptive-memory-feature-store-promotion-drift.md
-- (the in-memory reference backends this persists) and
-- architecture/decisions/0002-canonical-schema-technology.md /
-- 0004-sqlite-now-postgres-production.md (the portability discipline).
--
-- SEPARATE FILE, not an addition to packages/canonical/sql/schema_v0_1.sql:
-- these tables are Program D runtime state (feature values, promotion ledger),
-- not the canonical contract. They carry no tenant_id and no foreign key into
-- the canonical schema, so a Program D store can be opened against a database
-- that has never seen the canonical tables -- which is exactly how the
-- conformance suite opens it.
--
-- PORTABLE SUBSET ONLY (ADR-0002): no JSONB, no SERIAL/AUTOINCREMENT, no ENUM
-- types (CHECK ... IN (...) instead), no Postgres-only functions, no PostGIS.
-- This file must run unmodified on SQLite (the demo/reference engine) and on
-- PostgreSQL 17 (the pinned production target).
--
-- Three portability choices worth naming:
--
--  1. `DOUBLE PRECISION`, not `REAL`, for every metric/feature value. On SQLite
--     `REAL` is a 64-bit IEEE double, but on PostgreSQL `REAL` is float4 --
--     32-bit -- so the same write would read back with LESS precision on the
--     production engine than on the reference one. `DOUBLE PRECISION` is float8
--     on PostgreSQL and takes REAL affinity on SQLite (its declared-type rule
--     matches the substring "DOUB"), so a value round-trips bit-identically on
--     both. That matters here in a way it does not for a schedule's objective
--     value: the feature store's whole claim is that a past as-of read is
--     BIT-IDENTICAL, and a silently narrowed float would break that claim on
--     one engine only.
--
--  2. Timestamps are ISO-8601 UTC TEXT, as in the canonical schema, and the
--     Python layer writes them in a FIXED-WIDTH canonical form
--     (YYYY-MM-DDTHH:MM:SS.ffffff+00:00, see packages/core/feature_store.py
--     `_iso_utc`). Fixed width is what makes lexicographic string ordering
--     identical to chronological ordering, so the leakage guarantee's strict
--     `knowledge_time < as_of` can be evaluated by the DATABASE, in SQL,
--     identically on both engines -- not filtered in Python after an
--     unconstrained fetch.
--
--  3. Ordering columns (`write_sequence`, `decision_sequence`, ...) are plain
--     INTEGERs assigned by the application, not SERIAL/IDENTITY/AUTOINCREMENT,
--     mirroring how packages/canonical/storage.py assigns `decision_events.
--     sequence`. Auto-increment spellings differ per engine; an explicit
--     sequence is portable AND makes "the ledger is complete and in order" a
--     checkable property of the stored rows rather than of engine internals.
--
-- Every CREATE uses IF NOT EXISTS because two independent stores (the feature
-- store and the promotion ledger) may be opened over the SAME database, and
-- because reopening a store on an existing database is the persistence claim
-- under test -- neither may fail on "table already exists".

-- Append-only point-in-time feature values. A correction is a NEW row with a
-- later (or equal) knowledge_time, never an UPDATE: there is no UPDATE or
-- DELETE against this table anywhere in packages/core, on purpose, exactly as
-- for the canonical decision_events ledger.
--
-- `knowledge_time` is when the value BECAME KNOWN. An as-of read at label time
-- t admits a row only when knowledge_time < t, strictly. `write_sequence` is
-- the per-(entity, feature) append order and breaks ties at an identical
-- knowledge_time in favour of the last write (a correction recorded at the same
-- instant supersedes what it corrects -- the canonical "latest recorded version
-- wins" rule).
CREATE TABLE IF NOT EXISTS feature_values (
    entity_id       TEXT NOT NULL,
    feature_name    TEXT NOT NULL,
    value           DOUBLE PRECISION NOT NULL,
    knowledge_time  TEXT NOT NULL,
    write_sequence  INTEGER NOT NULL CHECK (write_sequence >= 1),
    PRIMARY KEY (entity_id, feature_name, write_sequence)
);

-- The as-of read's access path: (entity, feature) then time then append order,
-- which is exactly the ORDER BY the strict-past query uses.
CREATE INDEX IF NOT EXISTS ix_feature_values_as_of
    ON feature_values (entity_id, feature_name, knowledge_time, write_sequence);

-- The promotion ledger: every evaluated gate, promoted or not. Append-only and
-- globally ordered by `decision_sequence` -- it is an audit trail, so a rejected
-- challenger is recorded just as durably as a promoted one, and "what was
-- decided, in what order" is answerable after a restart.
CREATE TABLE IF NOT EXISTS promotion_decisions (
    decision_sequence  INTEGER NOT NULL PRIMARY KEY CHECK (decision_sequence >= 1),
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
    rationale          TEXT NOT NULL
);

-- Recorded demotions of the serving champion back to a prior one.
CREATE TABLE IF NOT EXISTS promotion_rollbacks (
    rollback_sequence  INTEGER NOT NULL PRIMARY KEY CHECK (rollback_sequence >= 1),
    task               TEXT NOT NULL,
    from_champion_id   TEXT NOT NULL,
    to_champion_id     TEXT NOT NULL,
    decided_at         TEXT NOT NULL,
    reason             TEXT NOT NULL
);

-- Current serving roles. Unlike the two ledgers above these are MUTABLE
-- pointers (one champion per task, at most one canary per task): the ledger is
-- the history, these tables are the present. Every mutation of them is
-- accompanied by a ledger row.
CREATE TABLE IF NOT EXISTS promotion_champions (
    task         TEXT NOT NULL PRIMARY KEY,
    champion_id  TEXT NOT NULL
);

-- The rollback stack: prior champions for a task, most recent = highest
-- stack_position. `rollback` pops the top entry.
CREATE TABLE IF NOT EXISTS promotion_champion_history (
    task            TEXT NOT NULL,
    stack_position  INTEGER NOT NULL CHECK (stack_position >= 1),
    champion_id     TEXT NOT NULL,
    PRIMARY KEY (task, stack_position)
);

-- The challenger pool. PRIMARY KEY (task, model_version_id) makes enrolling the
-- same version twice a no-op at the database layer, not merely in application
-- code; `enrol_sequence` preserves enrolment order for reads.
CREATE TABLE IF NOT EXISTS promotion_challengers (
    task              TEXT NOT NULL,
    model_version_id  TEXT NOT NULL,
    enrol_sequence    INTEGER NOT NULL CHECK (enrol_sequence >= 1),
    PRIMARY KEY (task, model_version_id)
);

-- At most one canary per task (PRIMARY KEY on task). The CHECK restates the
-- controller's [0, 1) rule at the database layer: a fraction of 1 would just be
-- the champion, so it can never be stored, even by a caller that bypassed the
-- Python validation.
CREATE TABLE IF NOT EXISTS promotion_canaries (
    task              TEXT NOT NULL PRIMARY KEY,
    model_version_id  TEXT NOT NULL,
    traffic_fraction  DOUBLE PRECISION NOT NULL
        CHECK (traffic_fraction >= 0 AND traffic_fraction < 1)
);
