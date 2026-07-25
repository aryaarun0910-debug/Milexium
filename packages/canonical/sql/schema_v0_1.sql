-- Canonical schema, contract version 0.1.0.
-- See architecture/decisions/0002-canonical-schema-technology.md and
-- architecture/decisions/0004-sqlite-now-postgres-production.md.
--
-- Portable subset only: no JSONB, no Postgres-only functions, no ENUM types
-- (CHECK ... IN (...) instead), no PostGIS spatial types. This file must run
-- unmodified on SQLite (the demo target) and PostgreSQL 17 (the pinned
-- production target). Timestamps are stored as ISO-8601 UTC strings
-- ("...Z" suffix) for portability; the Python layer in entities.py/time.py
-- is the source of truth for what is a *valid* timestamp, this schema only
-- enforces presence and type.
--
-- A field-level TEXT type is used for every id (UUIDv7 strings, per
-- packages/canonical/ids.py) rather than a native UUID type, again for
-- portability -- PostgreSQL's UUID type is fine but SQLite has none, and a
-- generated/typed column would silently diverge between engines.

CREATE TABLE tenants (
    tenant_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE service_requests (
    request_id              TEXT NOT NULL,
    version                 INTEGER NOT NULL CHECK (version >= 1),
    tenant_id                TEXT NOT NULL REFERENCES tenants(tenant_id),
    rider_ref                TEXT NOT NULL,
    pickup_zone              TEXT NOT NULL,
    dropoff_zone             TEXT NOT NULL,
    mobility_device          TEXT,
    requested_at             TEXT NOT NULL,
    negotiated_window_start  TEXT,
    negotiated_window_end    TEXT,
    scheduled_pickup_at      TEXT,
    predicted_pickup_at      TEXT,
    actual_pickup_at         TEXT,
    status                   TEXT NOT NULL CHECK (status IN
        ('requested','negotiated','scheduled','in_progress','completed','denied','cancelled','no_show')),
    recorded_at              TEXT NOT NULL,
    corrects_version         INTEGER,
    PRIMARY KEY (request_id, version)
);
-- A correction is a new row (request_id, version+1); the original row is
-- never UPDATEd or DELETEd by application code. This table has no UPDATE
-- statement anywhere in packages/canonical on purpose.

CREATE TABLE vehicles (
    vehicle_id            TEXT PRIMARY KEY,
    tenant_id             TEXT NOT NULL REFERENCES tenants(tenant_id),
    capacity_ambulatory   INTEGER NOT NULL CHECK (capacity_ambulatory >= 0),
    capacity_wheelchair   INTEGER NOT NULL CHECK (capacity_wheelchair >= 0),
    accessibility_equipment TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE drivers (
    driver_id   TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL REFERENCES tenants(tenant_id),
    shift_start TEXT NOT NULL,
    shift_end   TEXT NOT NULL
);

CREATE TABLE policies (
    policy_id      TEXT NOT NULL,
    version        INTEGER NOT NULL CHECK (version >= 1),
    tenant_id      TEXT NOT NULL REFERENCES tenants(tenant_id),
    name           TEXT NOT NULL,
    config_json    TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    PRIMARY KEY (policy_id, version)
);

CREATE TABLE model_versions (
    model_version_id           TEXT PRIMARY KEY,
    tenant_id                  TEXT NOT NULL REFERENCES tenants(tenant_id),
    task                       TEXT NOT NULL,
    training_data_manifest_hash TEXT NOT NULL,
    feature_schema_version     TEXT NOT NULL,
    evaluation_window_start    TEXT NOT NULL,
    evaluation_window_end      TEXT NOT NULL,
    artifact_hash              TEXT NOT NULL
);

CREATE TABLE forecast_vintages (
    tenant_id         TEXT NOT NULL REFERENCES tenants(tenant_id),
    model_version_id  TEXT NOT NULL REFERENCES model_versions(model_version_id),
    horizon_start     TEXT NOT NULL,
    horizon_end       TEXT NOT NULL,
    issued_at         TEXT NOT NULL,
    point_estimate    REAL NOT NULL,
    interval_low      REAL,
    interval_high     REAL,
    eventual_actual    REAL,
    PRIMARY KEY (tenant_id, model_version_id, horizon_start, issued_at)
);

CREATE TABLE schedule_runs (
    schedule_run_id  TEXT PRIMARY KEY,
    tenant_id        TEXT NOT NULL REFERENCES tenants(tenant_id),
    policy_id        TEXT NOT NULL,
    policy_version   INTEGER NOT NULL,
    solver_name      TEXT NOT NULL,
    solver_version   TEXT NOT NULL,
    seed             INTEGER NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('optimal','feasible','infeasible','timeout')),
    objective_value  REAL,
    bound            REAL,
    gap              REAL,
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    FOREIGN KEY (policy_id, policy_version) REFERENCES policies(policy_id, version)
);

CREATE TABLE decision_alternatives (
    schedule_run_id      TEXT NOT NULL REFERENCES schedule_runs(schedule_run_id),
    request_id           TEXT NOT NULL,
    candidate_vehicle_id TEXT REFERENCES vehicles(vehicle_id),
    feasible             INTEGER NOT NULL CHECK (feasible IN (0, 1)),
    failed_constraints   TEXT NOT NULL DEFAULT '[]',
    objective_delta      REAL
);

-- Append-only decision ledger. INSERT-only from application code; see
-- packages/canonical/events.py and architecture/decisions/0003-....md.
-- UNIQUE(tenant_id, aggregate_id, sequence) makes a sequence gap or a
-- duplicate sequence a constraint violation, not just an application bug;
-- UNIQUE(tenant_id, aggregate_id, idempotency_key) does the same for a
-- retried command with a fresh sequence number.
CREATE TABLE decision_events (
    event_id        TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES tenants(tenant_id),
    aggregate_id    TEXT NOT NULL,
    aggregate_type  TEXT NOT NULL,
    sequence        INTEGER NOT NULL CHECK (sequence >= 1),
    occurred_at     TEXT NOT NULL,
    actor_type      TEXT NOT NULL CHECK (actor_type IN ('system','human')),
    actor_id        TEXT NOT NULL,
    event_type      TEXT NOT NULL CHECK (event_type IN
        ('recommendation','rejection','override','outcome_recorded')),
    payload_json    TEXT NOT NULL,
    reason_codes    TEXT NOT NULL DEFAULT '[]',
    idempotency_key TEXT,
    prev_hash       TEXT,
    hash            TEXT NOT NULL,
    UNIQUE (tenant_id, aggregate_id, sequence),
    UNIQUE (tenant_id, aggregate_id, idempotency_key)
);

-- `vehicle_ref` / `run_ref` are the canonical home ADR-0038 found missing: the
-- vehicle/run assignment lived only on the Connect-layer OperatorTripRecord and
-- was recorded as a `dropped` semantic loss on every row, so the one field the
-- deadhead teardown depends on (it chains ONE vehicle's consecutive trips) could
-- not survive a write to MilexiumDB. Additive and NULLABLE: an export that named
-- neither is unattributable, and that is recorded as absence, never back-filled.
-- Plain TEXT for the same reason vehicle_observations.vehicle_ref is -- they name
-- the SOURCE system's vehicle/run, not a Milexium `Vehicle` aggregate, so there
-- is deliberately no REFERENCES vehicles(vehicle_id) here. Portable subset only:
-- nullable TEXT runs identically on SQLite and PostgreSQL 17.
CREATE TABLE outcomes (
    tenant_id                    TEXT NOT NULL REFERENCES tenants(tenant_id),
    request_id                   TEXT NOT NULL,
    served                       INTEGER NOT NULL CHECK (served IN (0, 1)),
    actual_pickup_at             TEXT,
    on_time                      INTEGER CHECK (on_time IN (0, 1)),
    excess_ride_time_minutes     REAL,
    deadhead_minutes             REAL,
    vehicle_ref                  TEXT,
    run_ref                      TEXT,
    PRIMARY KEY (tenant_id, request_id)
);

CREATE TABLE outbox (
    tenant_id     TEXT NOT NULL REFERENCES tenants(tenant_id),
    event_id      TEXT NOT NULL REFERENCES decision_events(event_id),
    destination   TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('pending','sent','failed')),
    dispatched_at TEXT,
    PRIMARY KEY (tenant_id, event_id, destination)
);

-- Operational / telemetry observations (request-INDEPENDENT), added to close the
-- ADR-0031 gap: (trip,stop,vehicle)-keyed telemetry (GTFS-Realtime and every
-- AVL/TODS source like it) carries no rider request, so it cannot honestly key on
-- a ServiceRequest. These tables key on their own observation_id and carry the
-- operational context (position, occupancy, status, predicted times, delays) that
-- the rider-request-keyed `outcomes` table had no home for.
--
-- PORTABILITY (ADR-0002): vehicle position is stored here as PLAIN lat/lon REAL
-- columns so this file still runs unmodified on SQLite AND Postgres. There is NO
-- PostGIS/geometry type here. The geometry(Point,4326) column, its GiST index, and
-- the population from lat/lon live ONLY in sql/postgis_postgres.sql, applied
-- separately by observation_store.py -- exactly the split rls_postgres.sql uses.
-- The BETWEEN/>=0 CHECKs mirror the Python-layer validators in entities.py; the
-- Python layer remains the source of truth, this schema enforces presence/range.
CREATE TABLE vehicle_observations (
    observation_id        TEXT PRIMARY KEY,
    tenant_id             TEXT NOT NULL REFERENCES tenants(tenant_id),
    vehicle_ref           TEXT,
    trip_ref              TEXT,
    route_ref             TEXT,
    stop_ref              TEXT,
    current_status        TEXT,
    latitude              REAL CHECK (latitude IS NULL OR (latitude BETWEEN -90 AND 90)),
    longitude             REAL CHECK (longitude IS NULL OR (longitude BETWEEN -180 AND 180)),
    bearing               REAL,
    speed                 REAL,
    occupancy_status      TEXT,
    occupancy_percentage  INTEGER CHECK (occupancy_percentage IS NULL OR occupancy_percentage >= 0),
    observed_at           TEXT NOT NULL,
    recorded_at           TEXT NOT NULL
);

CREATE TABLE stop_time_observations (
    observation_id          TEXT PRIMARY KEY,
    tenant_id               TEXT NOT NULL REFERENCES tenants(tenant_id),
    trip_ref                TEXT,
    route_ref               TEXT,
    stop_ref                TEXT,
    stop_sequence           INTEGER CHECK (stop_sequence IS NULL OR stop_sequence >= 0),
    schedule_relationship   TEXT,
    predicted_arrival_at    TEXT,
    predicted_departure_at  TEXT,
    observed_arrival_at     TEXT,
    observed_departure_at   TEXT,
    arrival_delay_seconds   INTEGER,
    departure_delay_seconds INTEGER,
    observed_at             TEXT NOT NULL,
    recorded_at             TEXT NOT NULL
);

-- SCHEDULING family (request-INDEPENDENT), the second half of the ADR-0031 gap.
-- ADR-0035 gave telemetry a home -- what a vehicle was OBSERVED doing. These three
-- tables give the other half a home: what a vehicle and an operator were ASSIGNED
-- to do. TODS (runs, blocks, pieces-of-work, deadheads) had no canonical home for
-- any of it, which is why ADR-0031/0035 both left TODS and NeTEx Specified rather
-- than half-building adapters that would route most of the standard to loss.
--
-- ADDITIVE ONLY: no existing table or column above is altered by this family.
--
-- Every *_ref column is the SOURCE system's identifier as the agency writes it
-- (block id, run id, vehicle number, garage code), so there is deliberately no
-- REFERENCES vehicles(vehicle_id) anywhere below -- the same judgment
-- outcomes.vehicle_ref and vehicle_observations.vehicle_ref already make. The only
-- foreign keys are to tenants (the isolation boundary) and to blocks (a genuine
-- canonical parent, minted by this repository).
--
-- PORTABILITY (ADR-0002): TEXT ids, ISO-8601 UTC strings for timestamps, and
-- CHECK ... IN (...) instead of an ENUM type -- so this file still runs unmodified
-- on SQLite and on PostgreSQL 17. Row-level security for these three tables is
-- Postgres-only and therefore lives in sql/rls_postgres.sql, applied separately;
-- it is NOT optional, a tenant-scoped table with no policy is the exact defect
-- ADR-0037 had to fix retroactively for the observation tables.
CREATE TABLE blocks (
    block_id     TEXT PRIMARY KEY,
    tenant_id    TEXT NOT NULL REFERENCES tenants(tenant_id),
    block_ref    TEXT,
    service_ref  TEXT,
    vehicle_ref  TEXT,
    garage_ref   TEXT,
    pull_out_at  TEXT NOT NULL,
    pull_in_at   TEXT NOT NULL,
    recorded_at  TEXT NOT NULL
);

-- One row per (run, piece), matching TODS runs_pieces: a run has no attribute of
-- its own beyond the pieces that share its run_ref, so there is no `runs` table for
-- the same fact to disagree with. run_ref is NULLABLE and absence means the export
-- did not say -- the piece is unattributable, never back-filled onto a neighbour.
-- block_id is a nullable FK: a crew export legitimately arrives before the vehicle
-- assignment it references, and block_ref preserves what the source said meanwhile.
CREATE TABLE run_pieces (
    run_piece_id   TEXT PRIMARY KEY,
    tenant_id      TEXT NOT NULL REFERENCES tenants(tenant_id),
    run_ref        TEXT,
    piece_ref      TEXT,
    piece_sequence INTEGER CHECK (piece_sequence IS NULL OR piece_sequence >= 0),
    operator_ref   TEXT,
    block_id       TEXT REFERENCES blocks(block_id),
    block_ref      TEXT,
    vehicle_ref    TEXT,
    start_type     TEXT,
    end_type       TEXT,
    started_at     TEXT NOT NULL,
    ended_at       TEXT NOT NULL,
    recorded_at    TEXT NOT NULL
);

-- Non-revenue movement. started_at/ended_at/run_ref carry the names
-- packages/replay/teardown.py already uses for its VehicleSegment inputs, so a
-- stored segment maps onto the teardown field-for-field instead of being
-- translated. deadhead_type is NOT NULL with a CHECK because it is the field a
-- consumer branches on; 'other' is the honest landing place for a source that did
-- not classify the movement, never a guess at 'interline'.
CREATE TABLE deadhead_segments (
    deadhead_segment_id TEXT PRIMARY KEY,
    tenant_id           TEXT NOT NULL REFERENCES tenants(tenant_id),
    deadhead_ref        TEXT,
    block_id            TEXT REFERENCES blocks(block_id),
    block_ref           TEXT,
    run_ref             TEXT,
    vehicle_ref         TEXT,
    deadhead_type       TEXT NOT NULL CHECK (deadhead_type IN
        ('pull_out','pull_in','interline','relief','repositioning','other')),
    from_stop_ref       TEXT,
    to_stop_ref         TEXT,
    started_at          TEXT NOT NULL,
    ended_at            TEXT NOT NULL,
    recorded_at         TEXT NOT NULL
);

-- THE DURABLE LIFECYCLE RECORD (MX-A-LIFECYCLE-RECORD-010).
--
-- `service_requests` above stores WHAT a request currently looks like, one row
-- per version. It does not store the MOVE: that request R went
-- requested -> negotiated at 09:14:03 because the 08:00 window had no accessible
-- capacity, then negotiated -> scheduled at 09:14:07. That move -- with its
-- decision instant, its actor and its reason codes -- is what this table holds,
-- and it is the thing the phrase "recorded at the moment of the decision rather
-- than reconstructed afterwards" actually refers to.
--
-- APPEND-ONLY. There is no UPDATE and no DELETE statement against this table
-- anywhere in packages/canonical, deliberately, and no test-only tamper helper
-- either (`decision_events` has one; this table does not, so "append-only" needs
-- no exception clause). A correction is a further transition, never an edit.
--
-- TWO CLOCKS. `decided_at` is valid time (when the decision was made);
-- `recorded_at` is transaction time (when this row was written). Note what is
-- NOT here: neither column has a DEFAULT. That absence is the schema-level half
-- of the decision-time guarantee -- the database itself cannot stamp a row -- and
-- conformance/property-tests/test_lifecycle_record.py reads it back out of
-- information_schema rather than trusting this comment.
--
-- THE CHECK AND WHY THE FORMAT MATTERS. `recorded_at >= decided_at` is a TEXT
-- comparison, and on PostgreSQL a TEXT comparison runs under the database
-- collation rather than byte order. Under this repository's dev collation
-- (English_United Kingdom.1252) '...T09:14:03.500000+00:00' compares as LESS
-- than '...T09:14:03+00:00' -- the wrong way round -- because punctuation and
-- digits are weighted differently. packages/canonical/lifecycle.py therefore
-- writes FIXED-WIDTH timestamps (always six fractional digits, always the
-- literal +00:00), so every value has identical punctuation in identical
-- positions and the comparison reduces to a digit-by-digit one that is correct
-- under any collation. The counterexample is pinned in the conformance suite.
-- This is the only table here whose timestamps are compared in SQL, which is why
-- it is the only one with the fixed-width convention; no existing column changes.
--
-- UNIQUE (tenant_id, request_id, sequence) makes a duplicate or a re-used chain
-- position a constraint violation rather than an application bug, exactly as the
-- same clause does on decision_events.
--
-- PORTABLE SUBSET (ADR-0002): TEXT ids, ISO-8601 UTC strings, CHECK ... IN (...)
-- instead of ENUM. The state vocabulary is spelled out twice in this file (here
-- and on service_requests.status) because that is what CHECK constraints cost;
-- a conformance test pins both against ServiceRequestState in both directions.
-- Row-level security is Postgres-only and lands in sql/rls_postgres.sql in the
-- SAME packet as this table -- ADR-0037's unguarded-table defect is not repeated.
CREATE TABLE request_state_transitions (
    transition_id           TEXT PRIMARY KEY,
    tenant_id               TEXT NOT NULL REFERENCES tenants(tenant_id),
    request_id              TEXT NOT NULL,
    sequence                INTEGER NOT NULL CHECK (sequence >= 1),
    from_state              TEXT NOT NULL CHECK (from_state IN
        ('requested','negotiated','scheduled','in_progress','completed','denied','cancelled','no_show')),
    to_state                TEXT NOT NULL CHECK (to_state IN
        ('requested','negotiated','scheduled','in_progress','completed','denied','cancelled','no_show')),
    decided_at              TEXT NOT NULL,
    recorded_at             TEXT NOT NULL,
    actor_type              TEXT NOT NULL CHECK (actor_type IN ('system','human')),
    actor_id                TEXT NOT NULL,
    reason_codes            TEXT NOT NULL DEFAULT '[]',
    requested_window_start  TEXT,
    requested_window_end    TEXT,
    negotiated_window_start TEXT,
    negotiated_window_end   TEXT,
    CHECK (recorded_at >= decided_at),
    UNIQUE (tenant_id, request_id, sequence)
);
