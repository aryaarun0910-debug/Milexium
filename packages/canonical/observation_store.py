"""PostGIS-backed store for operational observations, targeting the container (5433).

Program A + C follow-up for MX-A-OPS-ENTITY-002 / ADR-0031. This is the spatial
counterpart to `postgres_storage.py`, and deliberately ADDITIVE to it:

- `postgres_storage.PostgresCanonicalStore` targets the *natively installed*
  PostgreSQL 17 on host port 5432, as the deliberately non-superuser
  `milexium_dev` role (ADR-0006), and applies row-level security. It is untouched
  by this packet.
- This store targets the *containerized PostGIS* on host port 5433 (ADR-0004/0032),
  reading its credentials from `infra/compose/.env` (gitignored), because that is
  the only instance in the estate with the PostGIS extension. It exists to prove
  the round-trip for the operational entity family: `VehicleObservation` (with
  geometry) and `StopTimeObservation` (without -- a stop-time observation has no
  position of its own), nothing more.

It applies the PORTABLE `sql/schema_v0_1.sql` (lat/lon as REAL, SQLite-safe) and
THEN the Postgres-only `sql/postgis_postgres.sql` extension (a geometry(Point,4326)
column + GiST index), exactly the separation `rls_postgres.sql` uses -- the
geometry never touches the portable base DDL (ADR-0002). It inserts a
`VehicleObservation`, DERIVES its geometry from the stored lat/lon columns (the
geometry is never passed in from Python, so the REAL -> geometry derivation itself
is under test), and a spatial query (`ST_DWithin`) reads it back.

Test-isolation follows `postgres_storage.py`: a disposable per-run schema
`mx_<uuid>` created at construction and torn down with `DROP SCHEMA ... CASCADE`,
so parallel runs never collide and nothing survives a mid-test failure. The
`search_path` is set to `<schema>, public` so the unqualified `geometry` type and
ST_* functions resolve from the postgis install in `public`, while table names
resolve to the disposable schema.

Never called from non-test code; it is a conformance/round-trip harness.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg import sql

from packages.canonical.entities import StopTimeObservation, Tenant, VehicleObservation
from packages.canonical.ids import TenantId

_SCHEMA_PATH = Path(__file__).parent / "sql" / "schema_v0_1.sql"
_POSTGIS_PATH = Path(__file__).parent / "sql" / "postgis_postgres.sql"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE_ENV = _REPO_ROOT / "infra" / "compose" / ".env"


def _read_compose_env() -> dict[str, str]:
    """Parse infra/compose/.env into a dict. Returns {} if absent. Mirrors
    packages/estate/object_store.py's reader -- creds are read at runtime, never
    hardcoded or committed."""
    if not _COMPOSE_ENV.exists():
        return {}
    out: dict[str, str] = {}
    for line in _COMPOSE_ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def _iso_or_none(value: datetime | None) -> str | None:
    """Nullable timestamps are stored as ISO-8601 UTC TEXT (schema_v0_1.sql's
    portable convention) and stay SQL NULL when absent -- an unknown time is
    never written as an empty string or an epoch-zero placeholder."""
    return value.isoformat() if value is not None else None


def _parse_or_none(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def is_reachable(
    *, host: str = "localhost", port: int = 5433, connect_timeout: float = 2.0
) -> bool:
    """Best-effort connectivity probe for the containerized PostGIS. Lets the
    conformance suite skip cleanly (not fail) when infra/compose/.env is absent or
    the container is not up -- exactly the stance test_object_store.py takes."""
    env = _read_compose_env()
    password = env.get("POSTGRES_PASSWORD")
    if not password:
        return False
    try:
        conn = psycopg.connect(
            host=host,
            port=port,
            dbname=env.get("POSTGRES_DB", "milexium_dev"),
            user=env.get("POSTGRES_USER", "milexium_dev"),
            password=password,
            connect_timeout=connect_timeout,
        )
        conn.close()
        return True
    except Exception:
        return False


class PostgisObservationStore:
    """PostGIS-backed store for VehicleObservation, applying the portable schema
    plus the geometry extension against the 5433 container."""

    def __init__(self, connection: psycopg.Connection, *, schema: str | None = None) -> None:
        self._conn = connection
        self._schema = schema or f"mx_{uuid.uuid4().hex}"
        self._create_schema_and_apply_ddl()

    @classmethod
    def connect(
        cls, *, host: str = "localhost", port: int = 5433, schema: str | None = None
    ) -> "PostgisObservationStore":
        env = _read_compose_env()
        password = env.get("POSTGRES_PASSWORD")
        if not password:
            raise RuntimeError(
                "POSTGRES_PASSWORD not found in infra/compose/.env -- the containerized "
                "PostGIS is not configured"
            )
        connection = psycopg.connect(
            host=host,
            port=port,
            dbname=env.get("POSTGRES_DB", "milexium_dev"),
            user=env.get("POSTGRES_USER", "milexium_dev"),
            password=password,
        )
        return cls(connection, schema=schema)

    def _create_schema_and_apply_ddl(self) -> None:
        ident = sql.Identifier(self._schema)
        with self._conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(ident))
            # public is on the search_path so the geometry type + ST_* functions
            # (postgis is installed in public on the container) resolve, while
            # unqualified table names land in the disposable schema.
            cur.execute(sql.SQL("SET search_path TO {}, public").format(ident))
            cur.execute(_SCHEMA_PATH.read_text(encoding="utf-8"))
            # The geometry column/index/population is Postgres-only, so it is a
            # separate file applied only here -- never in the portable
            # schema_v0_1.sql (which must also run on SQLite). Exactly the
            # rls_postgres.sql pattern.
            cur.execute(_POSTGIS_PATH.read_text(encoding="utf-8"))
        self._conn.commit()

    def drop_schema(self) -> None:
        """Test/teardown helper: drops this instance's dedicated schema and
        everything in it. Never called from non-test code."""
        ident = sql.Identifier(self._schema)
        with self._conn.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(ident))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def create_tenant(self, tenant: Tenant) -> None:
        self._conn.execute(
            "INSERT INTO tenants (tenant_id, name, created_at) VALUES (%s, %s, %s)",
            (str(tenant.tenant_id), tenant.name, tenant.created_at.isoformat()),
        )
        self._conn.commit()

    def insert_vehicle_observation(self, obs: VehicleObservation) -> None:
        """Insert the PORTABLE columns (lat/lon as REAL -- identical to what SQLite
        would store), then DERIVE the PostGIS geometry from those stored columns
        with the same ST_SetSRID(ST_MakePoint(lon,lat),4326) expression as
        postgis_postgres.sql. The geometry is computed from the base columns, not
        passed in as a geometry, so the REAL -> geometry derivation is what the
        spatial round-trip proves."""
        self._conn.execute(
            "INSERT INTO vehicle_observations (observation_id, tenant_id, vehicle_ref, "
            "trip_ref, route_ref, stop_ref, current_status, latitude, longitude, bearing, "
            "speed, occupancy_status, occupancy_percentage, observed_at, recorded_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                str(obs.observation_id),
                str(obs.tenant_id),
                obs.vehicle_ref,
                obs.trip_ref,
                obs.route_ref,
                obs.stop_ref,
                obs.current_status,
                obs.latitude,
                obs.longitude,
                obs.bearing,
                obs.speed,
                obs.occupancy_status,
                obs.occupancy_percentage,
                obs.observed_at.isoformat(),
                obs.recorded_at.isoformat(),
            ),
        )
        self._conn.execute(
            "UPDATE vehicle_observations "
            "SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326) "
            "WHERE observation_id = %s AND latitude IS NOT NULL AND longitude IS NOT NULL",
            (str(obs.observation_id),),
        )
        self._conn.commit()

    def insert_stop_time_observation(self, obs: StopTimeObservation) -> None:
        """Insert the other half of the operational entity family (ADR-0031/0035).

        Deliberately simpler than `insert_vehicle_observation`: there is NO
        geometry step. A stop-time observation has no position of its own -- the
        position belongs to the stop it names, not to the observation -- so
        `postgis_postgres.sql` adds no geometry column to this table and the row
        is complete after this single INSERT. Portable columns only, exactly the
        set schema_v0_1.sql defines.

        Predicted and observed times are written to their own separate columns,
        preserving the entity's predicted-vs-observed discipline through storage:
        a GTFS-Realtime prediction never lands in an observed-time column.
        """
        self._conn.execute(
            "INSERT INTO stop_time_observations (observation_id, tenant_id, trip_ref, "
            "route_ref, stop_ref, stop_sequence, schedule_relationship, "
            "predicted_arrival_at, predicted_departure_at, observed_arrival_at, "
            "observed_departure_at, arrival_delay_seconds, departure_delay_seconds, "
            "observed_at, recorded_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                str(obs.observation_id),
                str(obs.tenant_id),
                obs.trip_ref,
                obs.route_ref,
                obs.stop_ref,
                obs.stop_sequence,
                obs.schedule_relationship,
                _iso_or_none(obs.predicted_arrival_at),
                _iso_or_none(obs.predicted_departure_at),
                _iso_or_none(obs.observed_arrival_at),
                _iso_or_none(obs.observed_departure_at),
                obs.arrival_delay_seconds,
                obs.departure_delay_seconds,
                obs.observed_at.isoformat(),
                obs.recorded_at.isoformat(),
            ),
        )
        self._conn.commit()

    def stop_time_observations(self, tenant_id: TenantId) -> tuple[StopTimeObservation, ...]:
        """Tenant-scoped read: every stop-time observation of `tenant_id`, in
        valid-time then stop order. The `tenant_id` filter is applied in SQL,
        never in Python after an unfiltered fetch -- the same discipline
        storage.py and postgres_storage.py state. Reconstructs the entity, so a
        successful round-trip proves the stored columns still validate against
        `StopTimeObservation` rather than merely being present."""
        cur = self._conn.execute(
            "SELECT observation_id, tenant_id, trip_ref, route_ref, stop_ref, stop_sequence, "
            "schedule_relationship, predicted_arrival_at, predicted_departure_at, "
            "observed_arrival_at, observed_departure_at, arrival_delay_seconds, "
            "departure_delay_seconds, observed_at, recorded_at "
            "FROM stop_time_observations WHERE tenant_id = %s "
            "ORDER BY observed_at, stop_sequence, observation_id",
            (str(tenant_id),),
        )
        rows = cur.fetchall()
        self._conn.commit()
        return tuple(
            StopTimeObservation(
                observation_id=r[0],
                tenant_id=r[1],
                trip_ref=r[2],
                route_ref=r[3],
                stop_ref=r[4],
                stop_sequence=r[5],
                schedule_relationship=r[6],
                predicted_arrival_at=_parse_or_none(r[7]),
                predicted_departure_at=_parse_or_none(r[8]),
                observed_arrival_at=_parse_or_none(r[9]),
                observed_departure_at=_parse_or_none(r[10]),
                arrival_delay_seconds=r[11],
                departure_delay_seconds=r[12],
                observed_at=datetime.fromisoformat(r[13]),
                recorded_at=datetime.fromisoformat(r[14]),
            )
            for r in rows
        )

    def observations_within(
        self,
        tenant_id: TenantId,
        *,
        latitude: float,
        longitude: float,
        radius_meters: float,
    ) -> list[dict]:
        """Spatial read: every observation of `tenant_id` whose geometry is within
        `radius_meters` of (latitude, longitude), nearest first. Casting to
        geography makes ST_DWithin/ST_Distance a true metric-distance test on the
        WGS84 sphere -- proving the geometry populated from lat/lon is spatially
        queryable, not just stored."""
        cur = self._conn.execute(
            "SELECT observation_id, vehicle_ref, latitude, longitude, "
            "ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography) AS dist_m "
            "FROM vehicle_observations "
            "WHERE tenant_id = %s AND geom IS NOT NULL "
            "AND ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography, %s) "
            "ORDER BY dist_m",
            (longitude, latitude, str(tenant_id), longitude, latitude, radius_meters),
        )
        rows = cur.fetchall()
        self._conn.commit()
        return [
            {
                "observation_id": r[0],
                "vehicle_ref": r[1],
                "latitude": r[2],
                "longitude": r[3],
                "distance_meters": r[4],
            }
            for r in rows
        ]
