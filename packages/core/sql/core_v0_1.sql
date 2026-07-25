-- Program D (Core / adaptive memory) schema, contract version 0.1.0.
-- See architecture/decisions/0034-adaptive-memory-feature-store-promotion-drift.md
-- (the in-memory reference backends this persists) and
-- architecture/decisions/0002-canonical-schema-technology.md /
-- 0004-sqlite-now-postgres-production.md (the portability discipline).
--
-- SEPARATE FILE, not an addition to packages/canonical/sql/schema_v0_1.sql:
-- these tables are Program D runtime state (feature values, promotion ledger),
-- not the canonical contract. They carry NO FOREIGN KEY into the canonical
-- schema, so a Program D store can be opened against a database that has never
-- seen the canonical tables -- which is exactly how the conformance suite opens
-- it.
--
-- TENANT ISOLATION (MX-D-TENANT-ISOLATION-006, closing an ADR-0041 limitation).
-- Every table below DOES carry `tenant_id TEXT NOT NULL`. ADR-0041 shipped these
-- tables without one and named the omission honestly: "multi-tenant Program D
-- state is a later slice ... that must be closed before a second operator's data
-- lands in them." That is this file's tenant column, and
-- packages/core/sql/core_rls_postgres.sql is the database-layer boundary that
-- makes it more than a WHERE clause. Three consequences are structural rather
-- than incidental, so they are named here:
--
--  a. `tenant_id` is TEXT, not a foreign key to `tenants`. The canonical
--     `tenants` table lives in a different contract and may not exist in the
--     database a Program D store is opened against (see above). The value is a
--     canonical `TenantId` string (UUIDv7) supplied by the caller; this schema
--     stores it opaquely, exactly as it stores `entity_id`.
--
--  b. `tenant_id` LEADS every primary key and every index. It is the highest-
--     selectivity column of every access path here, and putting it first means
--     the tenant predicate and the as-of predicate are served by ONE index --
--     the leakage guarantee's `knowledge_time < t` is not demoted to a filter
--     applied after a wider scan.
--
--  c. THE APPLICATION-ASSIGNED SEQUENCES ARE NOW PER-TENANT
--     (`decision_sequence`, `rollback_sequence`, `stack_position`,
--     `enrol_sequence`). This is forced, not stylistic: under row-level security
--     `SELECT MAX(decision_sequence) FROM promotion_decisions` sees only the
--     acting tenant's rows, so a GLOBAL sequence would be re-derived per tenant
--     and two tenants would collide on the same primary key -- the isolation
--     boundary and a global counter cannot both hold. Per-tenant is also the
--     better ledger: "complete and in order" is a claim about one operator's
--     audit trail, and a global counter would let a tenant infer another's
--     activity from the gaps in its own.
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
