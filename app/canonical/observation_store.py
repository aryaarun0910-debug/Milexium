"""PostGIS-backed store for operational observations, targeting the container (5433).

Program A + C follow-up for MX-A-OPS-ENTITY-002 / ADR-0031. This is the spatial
counterpart to `postgres_storage.py`, and deliberately ADDITIVE to it:

- `postgres_storage.PostgresCanonicalStore` targets the *natively installed*
  PostgreSQL 17 on host port 5432, as the deliberately non-superuser
  `milexium_dev` role (ADR-0006), and applies row-level security. It is untouched
  by this packet.
- This store targets the *containerized PostGIS* on host port 5433 (ADR-0004/0032),
  reading its credentials from `platform/infra/compose/.env` (gitignored), because that is
  the only instance in the estate with the PostGIS extension. It exists to prove
  the round-trip for the operational entity family: `VehicleObservation` (with
  geometry) and `StopTimeObservation` (without -- a stop-time observation has no
  position of its own), nothing more.

It applies the PORTABLE `sql/schema_v0_1.sql` (lat/lon as REAL, SQLite-safe),
THEN the Postgres-only `sql/postgis_postgres.sql` extension (a geometry(Point,4326)
column + GiST index), THEN the Postgres-only `sql/rls_postgres.sql` -- exactly the
separation those two files describe: the geometry and the policies never touch the
portable base DDL (ADR-0002). It inserts a `VehicleObservation`, DERIVES its
geometry from the stored lat/lon columns (the geometry is never passed in from
Python, so the REAL -> geometry derivation itself is under test), and a spatial
query (`ST_DWithin`) reads it back.

TENANT ISOLATION IS POLICY-ENFORCED HERE, NOT JUST WHERE-CLAUSE FILTERED
(MX-C-CONTAINER-RLS-005, closing the scope gap ADR-0037 recorded as open). Until
this packet, this store applied the portable schema plus the geometry extension
and nothing else: its reads filtered on `tenant_id` in the SQL text, so the
boundary was application code. A WHERE clause is application code; a policy is a
boundary. This store now applies the SAME `sql/rls_postgres.sql` the native store
applies -- the file itself, not a copy, so the container store cannot drift away
from the policies the native store enforces -- and calls `_use_tenant()` before
every read and write to set the `milexium.tenant_id` GUC those policies key on,
exactly as `PostgresCanonicalStore` does. The tenant_id WHERE clauses stay: two
independent boundaries, either alone sufficient.

WHY THIS STORE HAS TO `SET ROLE` (and the native store does not)
RLS binds neither superusers nor `BYPASSRLS` roles -- `FORCE` does not help,
because FORCE only subjects the table OWNER, and the bypass check is made first.
On the native PostgreSQL 17 that is a non-issue: `milexium_dev` there is
deliberately a plain, non-superuser role (ADR-0006). In the CONTAINER it is not:
the postgres/postgis image bootstraps `POSTGRES_USER` as the cluster's superuser,
so the credential in `platform/infra/compose/.env` holds both `rolsuper` and
`rolbypassrls`. Applying the policies while connected as that role would install
a boundary that binds nobody, and every isolation test would pass for the wrong
reason -- the same false green `rls_postgres.sql`'s header warns about, one level
up. So construction creates (idempotently) a deliberately unprivileged
`milexium_rls` role -- NOSUPERUSER, NOBYPASSRLS, NOLOGIN, reachable only via
`SET ROLE` -- makes it the OWNER of the disposable schema and everything in it,
and acts as it for the rest of the session. Owner, not merely user, so `FORCE` is
genuinely load-bearing here too rather than being masked by a plain permission
failure; `evidence/conformance/property-tests/test_postgis_rls.py` asserts the acting role
is unprivileged before it asserts anything else, and lifts FORCE to watch the
boundary collapse.

Test-isolation follows `postgres_storage.py`: a disposable per-run schema
`mx_<uuid>` created at construction and torn down with `DROP SCHEMA ... CASCADE`,
so parallel runs never collide and nothing survives a mid-test failure. The
`search_path` is set to `<schema>, public` so the unqualified `geometry` type and
ST_* functions resolve from the postgis install in `public`, while table names
resolve to the disposable schema.

Never called from non-test code; it is a evidence/conformance/round-trip harness.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg import sql

from app.canonical.entities import StopTimeObservation, Tenant, VehicleObservation
from app.canonical.ids import TenantId

_SCHEMA_PATH = Path(__file__).parent / "sql" / "schema_v0_1.sql"
_POSTGIS_PATH = Path(__file__).parent / "sql" / "postgis_postgres.sql"
_RLS_PATH = Path(__file__).parent / "sql" / "rls_postgres.sql"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE_ENV = _REPO_ROOT / "platform" / "infra" / "compose" / ".env"

# The deliberately unprivileged role this store acts as, so the policies it
# installs actually bind it. See "WHY THIS STORE HAS TO SET ROLE" above. NOLOGIN:
# it is never a connection identity, only a `SET ROLE` target, so it needs no
# password and cannot be logged into if it leaks.
_RLS_ROLE = "milexium_rls"


def _read_compose_env() -> dict[str, str]:
    """Parse platform/infra/compose/.env into a dict. Returns {} if absent. Mirrors
    app/estate/object_store.py's reader -- creds are read at runtime, never
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


def _application_credential(env: dict[str, str]) -> tuple[str, str | None]:
    """The credential the code should connect with: the UNPRIVILEGED application
    role when it is configured, otherwise the bootstrap superuser.

    ADR-0046 found that `POSTGRES_USER` is the cluster SUPERUSER on this image --
    it holds `rolbypassrls`, and superuser bypass is evaluated BEFORE
    `FORCE ROW LEVEL SECURITY`, so a connection using it silently ignores every
    tenant policy in the database. ADR-0052 provisions `milexium_app`
    (NOSUPERUSER, NOBYPASSRLS) so RLS binds at the CONNECTION level rather than
    depending on the store remembering to demote itself with SET ROLE.

    The superuser fallback is deliberate but narrow: a checkout whose
    platform/infra/compose/.env predates ADR-0052 still works rather than failing
    mysteriously. It is NOT a security position -- `test_postgis_rls.py` asserts
    the connected role is non-superuser and non-BYPASSRLS, so a run that silently
    fell back to the superuser fails loudly instead of passing for the wrong
    reason (the exact failure mode ADR-0046 was written about).
    """
    app_user = env.get("MILEXIUM_APP_USER")
    app_password = env.get("MILEXIUM_APP_PASSWORD")
    if app_user and app_password:
        return app_user, app_password
    return env.get("POSTGRES_USER", "milexium_dev"), env.get("POSTGRES_PASSWORD")


def is_reachable(
    *, host: str = "localhost", port: int = 5433, connect_timeout: float = 2.0
) -> bool:
    """Best-effort connectivity probe for the containerized PostGIS. Lets the
    conformance suite skip cleanly (not fail) when platform/infra/compose/.env is absent or
    the container is not up -- exactly the stance test_object_store.py takes."""
    env = _read_compose_env()
    user, password = _application_credential(env)
    if not password:
        return False
    try:
        conn = psycopg.connect(
            host=host,
            port=port,
            dbname=env.get("POSTGRES_DB", "milexium_dev"),
            user=user,
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
        #: The role this store's statements actually run as, and the OWNER of the
        #: disposable schema. `None` means the connecting credential was already
        #: unprivileged enough to be bound by RLS, so no `SET ROLE` was needed.
        self._acting_role: str | None = None
        self._create_schema_and_apply_ddl()

    @classmethod
    def connect(
        cls, *, host: str = "localhost", port: int = 5433, schema: str | None = None
    ) -> "PostgisObservationStore":
        env = _read_compose_env()
        user, password = _application_credential(env)
        if not password:
            raise RuntimeError(
                "no PostGIS credential found in platform/infra/compose/.env -- set "
                "MILEXIUM_APP_PASSWORD (preferred, ADR-0052) or POSTGRES_PASSWORD"
            )
        connection = psycopg.connect(
            host=host,
            port=port,
            dbname=env.get("POSTGRES_DB", "milexium_dev"),
            user=user,
            password=password,
        )
        return cls(connection, schema=schema)

    def _ensure_unprivileged_role(self) -> str | None:
        """Return the role this store should act as, creating it if necessary.

        Returns `None` when the connecting credential is ALREADY subject to RLS
        (neither superuser nor `BYPASSRLS`) -- then it can own and act on the
        schema directly, as `PostgresCanonicalStore` does against the native
        instance, and no role switch is warranted.

        Otherwise the credential bypasses every policy this store is about to
        install, so it provisions `milexium_rls`: NOSUPERUSER, NOBYPASSRLS,
        NOLOGIN. Creation is idempotent AND race-safe -- two conformance runs
        starting together would both see the role missing, so the `duplicate_object`
        handler, not a check-then-create, is what makes the loser survive. It runs
        in its own committed transaction so losing that race cannot abort the DDL
        that follows.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"
            )
            row = cur.fetchone()
            if row is not None and row[0] is False:
                return None
            cur.execute(
                sql.SQL(
                    "DO $$ BEGIN CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS "
                    "NOCREATEDB NOCREATEROLE; "
                    "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
                ).format(sql.Identifier(_RLS_ROLE))
            )
        self._conn.commit()
        return _RLS_ROLE

    def _create_schema_and_apply_ddl(self) -> None:
        ident = sql.Identifier(self._schema)
        self._acting_role = self._ensure_unprivileged_role()
        with self._conn.cursor() as cur:
            if self._acting_role is None:
                cur.execute(sql.SQL("CREATE SCHEMA {}").format(ident))
            else:
                # AUTHORIZATION *before* SET ROLE: the unprivileged role must OWN
                # the schema and therefore every table created in it below. Owner
                # rather than merely grantee is deliberate -- it is what makes
                # FORCE ROW LEVEL SECURITY the thing standing between tenants,
                # instead of an ordinary permission failure masking an absent
                # policy.
                cur.execute(
                    sql.SQL("CREATE SCHEMA {} AUTHORIZATION {}").format(
                        ident, sql.Identifier(self._acting_role)
                    )
                )
            # public is on the search_path so the geometry type + ST_* functions
            # (postgis is installed in public on the container) resolve, while
            # unqualified table names land in the disposable schema.
            cur.execute(sql.SQL("SET search_path TO {}, public").format(ident))
            if self._acting_role is not None:
                # Session-scoped, so it survives this store's per-operation
                # commits: every statement after this one -- DDL and DML alike --
                # runs as a role the policies below can actually constrain.
                cur.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(self._acting_role)))
            cur.execute(_SCHEMA_PATH.read_text(encoding="utf-8"))
            # The geometry column/index/population is Postgres-only, so it is a
            # separate file applied only here -- never in the portable
            # schema_v0_1.sql (which must also run on SQLite). Exactly the
            # rls_postgres.sql pattern.
            #
            # `CREATE EXTENSION IF NOT EXISTS postgis` inside it needs no
            # privilege when postgis is already installed (the postgis image
            # installs it into `public` at initdb): the IF NOT EXISTS short-circuit
            # is checked before the ownership check, so it is a NOTICE and a
            # no-op for the unprivileged role above.
            cur.execute(_POSTGIS_PATH.read_text(encoding="utf-8"))
            # THE SAME FILE the native store applies -- read, not copied. A
            # second, hand-maintained copy of these policies would be free to
            # drift from the ones the native store enforces, and a tenant
            # boundary that is only mostly the same boundary is not one.
            # Applied last so the geometry column exists before any policy is
            # evaluated against this table, and so postgis_postgres.sql's
            # back-fill UPDATE is not itself filtered by a not-yet-set GUC.
            cur.execute(_RLS_PATH.read_text(encoding="utf-8"))
        self._conn.commit()

    def _use_tenant(self, tenant_id: object) -> None:
        """Set the session's RLS key (`milexium.tenant_id`) to `tenant_id`.

        Identical contract to `PostgresCanonicalStore._use_tenant`, and required
        for the same reason: every policy in sql/rls_postgres.sql keys on this
        GUC, so without it the store would be acting as no tenant and the
        policies would (correctly) deny it everything. Session scope
        (`is_local=false`) means the value survives this store's per-operation
        commits, but every operation re-sets it first, so none depends on a value
        another left behind. `set_config` binds `tenant_id` as a parameter, so it
        is never string-interpolated into SQL."""
        self._conn.execute("SELECT set_config('milexium.tenant_id', %s, false)", (str(tenant_id),))

    def drop_schema(self) -> None:
        """Test/teardown helper: drops this instance's dedicated schema and
        everything in it. Never called from non-test code.

        `RESET ROLE` first: teardown must not be the one operation that can fail
        for want of privilege, and a test that deliberately left the acting role
        mid-experiment (lifted FORCE, say) still has to clean up completely."""
        ident = sql.Identifier(self._schema)
        with self._conn.cursor() as cur:
            cur.execute("RESET ROLE")
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(ident))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def create_tenant(self, tenant: Tenant) -> None:
        # A tenant registers itself: the GUC is the new tenant's own id, so the
        # `tenants` policy's WITH CHECK (tenant_id = GUC) permits exactly this
        # row and no other -- the same self-registration PostgresCanonicalStore
        # performs.
        self._use_tenant(tenant.tenant_id)
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
        spatial round-trip proves.

        Runs under the observation's OWN tenant as the acting GUC, so the
        `vehicle_observations` WITH CHECK admits this row -- and the geometry
        UPDATE that follows is governed by the same policy's USING clause, which
        is the point: the spatial column can only ever be populated on a row the
        acting tenant may already see."""
        self._use_tenant(obs.tenant_id)
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
        self._use_tenant(obs.tenant_id)
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
        valid-time then stop order. Reconstructs the entity, so a successful
        round-trip proves the stored columns still validate against
        `StopTimeObservation` rather than merely being present.

        Two independent boundaries hold, as in `postgres_storage.py`: the
        `stop_time_observations` RLS policy, keyed on the GUC set here and
        enforced by PostgreSQL itself, and the `tenant_id` WHERE clause below --
        applied in SQL, never in Python after an unfiltered fetch. Either alone
        is sufficient; the WHERE clause is kept precisely so it is not the only
        one."""
        self._use_tenant(tenant_id)
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
        queryable, not just stored.

        THE GEOMETRY PATH IS NOT A WAY AROUND THE POLICY. This is the one read on
        this store that could plausibly have become one: a spatial predicate is
        evaluated by PostGIS over a GiST index, and it is easy to assume an index
        scan sees rows a sequential scan would not. It does not. The policy's
        USING clause becomes part of the scan's own qualification, so the result
        is the INTERSECTION however the rows are reached; and because it is a
        security-barrier qual, a non-leakproof user predicate like ST_DWithin
        cannot even be evaluated ahead of it. The GUC set here is what gives that
        clause a tenant to match, and
        `evidence/conformance/property-tests/test_postgis_rls.py` proves the outcome
        empirically by running this very predicate with the `tenant_id` filter
        DELETED, rather than resting on the reasoning above."""
        self._use_tenant(tenant_id)
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
