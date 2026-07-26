-- HISTORICAL ARTIFACT -- schema version 1, the ADR-0041 (MX-D-PERSISTENCE-004)
-- shape of the Program D tables, BEFORE tenant isolation.
--
-- THIS FILE IS NEVER APPLIED TO A NEW DATABASE. `CoreDatabase.sqlite()` and
-- `CoreDatabase.postgres()` create databases at the CURRENT version
-- (app/core/sql/core_v0_1.sql) and nothing in app/core will ever
-- create this shape. It is kept for exactly two purposes:
--
--  1. It is the specification of what schema version 1 IS. `migrations.py`
--     detects a version-1 database by its column shape, and this file is where
--     that shape is written down in the form it actually shipped in -- so the
--     detector is checked against the real thing rather than against a
--     recollection of it.
--
--  2. evidence/conformance/property-tests/test_core_migrations.py creates a genuine
--     version-1 database from THIS FILE'S OWN BYTES and migrates it. A
--     hand-written approximation in the test would be free to drift from what
--     ADR-0041 shipped, and the migration would then be proved against a shape
--     no operator ever had.
--
-- The statements below are verbatim from the pre-tenant `core_v0_1.sql` (git
-- 896ca21^). Only the header comment is new. Note what is absent and what it
-- cost: no `tenant_id` on any table, so `decision_sequence`, `rollback_sequence`,
-- `stack_position` and `enrol_sequence` were GLOBAL counters and `task` alone was
-- the champion key -- two operators running `forecast.demand` would have shared
-- one champion pointer.

CREATE TABLE IF NOT EXISTS feature_values (
    entity_id       TEXT NOT NULL,
    feature_name    TEXT NOT NULL,
    value           DOUBLE PRECISION NOT NULL,
    knowledge_time  TEXT NOT NULL,
    write_sequence  INTEGER NOT NULL CHECK (write_sequence >= 1),
    PRIMARY KEY (entity_id, feature_name, write_sequence)
);

CREATE INDEX IF NOT EXISTS ix_feature_values_as_of
    ON feature_values (entity_id, feature_name, knowledge_time, write_sequence);

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

CREATE TABLE IF NOT EXISTS promotion_rollbacks (
    rollback_sequence  INTEGER NOT NULL PRIMARY KEY CHECK (rollback_sequence >= 1),
    task               TEXT NOT NULL,
    from_champion_id   TEXT NOT NULL,
    to_champion_id     TEXT NOT NULL,
    decided_at         TEXT NOT NULL,
    reason             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS promotion_champions (
    task         TEXT NOT NULL PRIMARY KEY,
    champion_id  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS promotion_champion_history (
    task            TEXT NOT NULL,
    stack_position  INTEGER NOT NULL CHECK (stack_position >= 1),
    champion_id     TEXT NOT NULL,
    PRIMARY KEY (task, stack_position)
);

CREATE TABLE IF NOT EXISTS promotion_challengers (
    task              TEXT NOT NULL,
    model_version_id  TEXT NOT NULL,
    enrol_sequence    INTEGER NOT NULL CHECK (enrol_sequence >= 1),
    PRIMARY KEY (task, model_version_id)
);

CREATE TABLE IF NOT EXISTS promotion_canaries (
    task              TEXT NOT NULL PRIMARY KEY,
    model_version_id  TEXT NOT NULL,
    traffic_fraction  DOUBLE PRECISION NOT NULL
        CHECK (traffic_fraction >= 0 AND traffic_fraction < 1)
);
