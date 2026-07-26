-- PostGIS spatial extension for vehicle_observations, contract v0.1.
-- See knowledge/architecture/decisions/0002-canonical-schema-technology.md (portable base
-- DDL) and 0004-sqlite-now-postgres-production.md / 0032 (containerized PostGIS).
--
-- WHY THIS FILE IS SEPARATE FROM schema_v0_1.sql (the same rationale rls_postgres.sql states)
-- schema_v0_1.sql is the *portable* DDL: it must run unmodified on both SQLite
-- (the demo engine) and PostgreSQL, so it may not contain a single Postgres-only
-- construct. PostGIS is Postgres-only, so vehicle position is stored in the base
-- schema as plain `latitude`/`longitude` REAL columns, and everything spatial
-- lives here: this file adds the geometry(Point,4326) column, a GiST spatial
-- index, and populates the geometry FROM those lat/lon columns. It is applied
-- ONLY by app/canonical/observation_store.py against the containerized
-- PostGIS on host port 5433 -- AFTER the portable schema, never on SQLite, never
-- inside schema_v0_1.sql. This is the exact SQLite-vs-Postgres split ADR-0002
-- requires, mirroring how rls_postgres.sql keeps row-level security out of the
-- portable base.
--
-- The store applies this inside its disposable per-run schema with
-- `search_path = <schema>, public`, so the unqualified `geometry` type and the
-- ST_* functions resolve from the postgis install (in `public` on the container)
-- while the table names resolve to the disposable schema. `CREATE EXTENSION IF
-- NOT EXISTS postgis` is a safe no-op where postgis is already installed (the
-- postgis/postgis image installs it into `public`).

CREATE EXTENSION IF NOT EXISTS postgis;

-- WGS84 / EPSG:4326 point geometry for the vehicle's live position.
ALTER TABLE vehicle_observations ADD COLUMN geom geometry(Point, 4326);

-- Populate the geometry from the portable lat/lon columns. ST_MakePoint takes
-- (x = longitude, y = latitude) order -- the classic lon/lat trap. Guarded on
-- geom IS NULL so it is idempotent and only fills rows written before/without the
-- geometry (at apply-time against an empty table this is a harmless no-op; the
-- store re-runs the same expression per inserted row).
UPDATE vehicle_observations
    SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
    WHERE latitude IS NOT NULL AND longitude IS NOT NULL AND geom IS NULL;

-- GiST index so a spatial predicate (ST_DWithin / bounding box) is index-backed.
CREATE INDEX vehicle_observations_geom_gist ON vehicle_observations USING GIST (geom);
