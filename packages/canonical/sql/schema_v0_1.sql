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

CREATE TABLE outcomes (
    tenant_id                    TEXT NOT NULL REFERENCES tenants(tenant_id),
    request_id                   TEXT NOT NULL,
    served                       INTEGER NOT NULL CHECK (served IN (0, 1)),
    actual_pickup_at             TEXT,
    on_time                      INTEGER CHECK (on_time IN (0, 1)),
    excess_ride_time_minutes     REAL,
    deadhead_minutes             REAL,
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
