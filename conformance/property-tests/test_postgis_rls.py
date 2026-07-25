"""Adversarial conformance: row-level security on the CONTAINERIZED PostGIS
(host port 5433), where vehicle position and occupancy actually live
(MX-C-CONTAINER-RLS-005).

WHAT GAP THIS CLOSES. ADR-0037 extended `sql/rls_postgres.sql` to the two
observation tables, and `conformance/property-tests/test_stop_time_observation_store.py`
proved those policies against the NATIVE PostgreSQL 17 on 5432. But that file was
applied only by `PostgresCanonicalStore`. `PostgisObservationStore` -- the store
that actually holds vehicle position, occupancy and the geometry derived from
them -- targets the container on 5433 and applied the portable schema plus
`postgis_postgres.sql` and nothing else. Its reads named `tenant_id` in the SQL
text, so the tenant boundary on the most sensitive operational data in the schema
(SensitivityClass.PRECISE_LOCATION) was a WHERE clause. A WHERE clause is
application code; a policy is a boundary. These tests exist to prove the boundary,
so every read below is RAW SQL with the `tenant_id` filter DELIBERATELY DELETED --
what is under test is the database policy, never a Python code path.

THREE WAYS THIS SUITE COULD PASS FOR THE WRONG REASON, each closed by a test
rather than argued away:

1. *The acting role bypasses RLS anyway.* This is not hypothetical here. The
   postgres/postgis image bootstraps `POSTGRES_USER` as the container cluster's
   SUPERUSER, so the credential in `infra/compose/.env` holds `rolsuper` and
   `rolbypassrls` -- and a superuser bypasses row security no matter what the
   policies say, `FORCE` included, because that check is made first. Under that
   credential every policy below is decoration and every assertion here would be
   measuring a WHERE clause that is no longer there. `test_the_acting_role_is_bound_by_row_security`
   asserts the store is acting as an unprivileged role before anything else is
   claimed.
2. *The owner bypasses the policy.* The acting role OWNS these tables, and a table
   owner bypasses RLS unless `FORCE` is set -- the false green
   `sql/rls_postgres.sql`'s own header is about.
   `test_force_row_level_security_is_load_bearing` lifts FORCE, watches the
   boundary collapse, and restores it.
3. *The block is passing on an empty table.* Every cross-tenant denial below is
   paired with a positive control proving the row it is not seeing exists and is
   visible to its own tenant.

THE SPATIAL PATH IS THE POINT. This store exists for the geometry, so a policy
that governed `SELECT ... WHERE tenant_id = ...` but not `ST_DWithin` would close
nothing that matters. `test_spatial_query_is_tenant_scoped_by_the_policy_alone`
runs the real ST_DWithin/geography predicate over a GiST-indexed column with NO
tenant filter at all, against a corridor two tenants both observe.

Skips cleanly (never fails) when psycopg is absent or the container is not up, so
CI stays green -- but a skip proves nothing, so the packet's evidence requirement
is that these RUN.

Status: Demonstrated only -- open public real-time transit data.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

psycopg = pytest.importorskip("psycopg")  # skip the whole module if absent

from psycopg import sql  # noqa: E402

from packages.canonical import (  # noqa: E402
    ObservationId,
    Tenant,
    TenantId,
    new_id,
)
from packages.canonical.observation_store import (  # noqa: E402
    PostgisObservationStore,
    _read_compose_env,
    is_reachable,
)

_OBSERVATION_TABLES = ["vehicle_observations", "stop_time_observations"]

# One point on a shared corridor. BOTH tenants observe a vehicle here, which is
# what happens when two agencies run the same street -- so a spatial query that
# leaked would leak visibly, rather than returning an empty set either way.
_BOSTON = (42.3311, -71.0905)


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _tenant(name: str) -> Tenant:
    return Tenant(tenant_id=new_id(TenantId), name=name, created_at=_utc(2026, 7, 24))


@pytest.fixture
def store() -> PostgisObservationStore:
    if not is_reachable():
        pytest.skip(
            "containerized PostGIS (5433) not reachable / infra/compose/.env absent -- "
            "dev stack not up"
        )
    try:
        st = PostgisObservationStore.connect()
    except Exception as exc:  # noqa: BLE001 -- any connection failure => skip, not fail
        pytest.skip(f"PostGIS not reachable ({type(exc).__name__}) -- dev stack not up")
    try:
        yield st
    finally:
        st.drop_schema()
        st.close()


def _set_session_tenant(store: PostgisObservationStore, tenant_id: object) -> None:
    """Point the session GUC at `tenant_id` directly -- exactly what an attacker
    holding the app credential, or a plain bug, could do -- so the raw reads below
    are governed by the policy and by nothing else."""
    store._conn.execute("SELECT set_config('milexium.tenant_id', %s, false)", (str(tenant_id),))


def _seed(store: PostgisObservationStore, tenant: Tenant, *, vehicle_ref: str) -> None:
    """Register `tenant` and give it one row in EACH observation table, by raw SQL,
    with the vehicle row's geometry populated at the shared corridor point.

    Deliberately not routed through the store's typed insert methods: those set
    the GUC themselves, and a test that leant on them would be proving the Python
    helper rather than the policy."""
    store.create_tenant(tenant)  # also points the GUC at this tenant
    store._conn.execute(
        "INSERT INTO vehicle_observations (observation_id, tenant_id, vehicle_ref, "
        "latitude, longitude, occupancy_status, observed_at, recorded_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            str(new_id(ObservationId)),
            str(tenant.tenant_id),
            vehicle_ref,
            _BOSTON[0],
            _BOSTON[1],
            "FULL",
            "2026-07-24T16:37:03+00:00",
            "2026-07-24T16:37:10+00:00",
        ),
    )
    store._conn.execute(
        "UPDATE vehicle_observations "
        "SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326) "
        "WHERE geom IS NULL AND latitude IS NOT NULL AND longitude IS NOT NULL"
    )
    store._conn.execute(
        "INSERT INTO stop_time_observations (observation_id, tenant_id, trip_ref, stop_ref, "
        "stop_sequence, observed_at, recorded_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (
            str(new_id(ObservationId)),
            str(tenant.tenant_id),
            "trip-44-0001",
            "1259",
            3,
            "2026-07-24T16:30:00+00:00",
            "2026-07-24T16:30:05+00:00",
        ),
    )
    store._conn.commit()


def _dwithin_vehicle_refs(store: PostgisObservationStore, *, radius_meters: float = 500) -> set:
    """The store's real spatial predicate with the `tenant_id = %s` filter REMOVED.

    This is the query that matters. If RLS did not reach the geometry path, this
    would return every tenant's vehicles standing on the corridor."""
    cur = store._conn.execute(
        "SELECT vehicle_ref FROM vehicle_observations "
        "WHERE geom IS NOT NULL "
        "AND ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography, %s)",
        (_BOSTON[1], _BOSTON[0], radius_meters),
    )
    refs = {row[0] for row in cur.fetchall()}
    store._conn.commit()
    return refs


# =========================================================================
# 0. The precondition everything else rests on
# =========================================================================


def test_the_acting_role_is_bound_by_row_security(store) -> None:
    """The container's own credential is a SUPERUSER -- so if the store acted as
    it, every policy below would be inert and this whole module would be a
    tautology.

    Superuser and BYPASSRLS are checked BEFORE ownership and before FORCE, so
    neither `ENABLE` nor `FORCE` can rescue a privileged connection. Asserting
    the acting role holds neither attribute is therefore the precondition for
    reading any other result in this file as evidence."""
    cur = store._conn.execute(
        "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
    )
    acting, is_super, bypasses = cur.fetchone()
    store._conn.commit()

    assert is_super is False, (
        f"the store is acting as superuser {acting!r}, which bypasses row security "
        "outright -- every isolation assertion in this module would pass for the "
        "wrong reason"
    )
    assert bypasses is False, f"acting role {acting!r} holds BYPASSRLS"


@pytest.mark.parametrize("table", _OBSERVATION_TABLES)
def test_the_acting_role_owns_the_observation_tables(store, table: str) -> None:
    """FORCE is only meaningful against the OWNER: for any other role the policy
    would never be the thing standing in the way, an ordinary privilege error
    would be, and `test_force_row_level_security_is_load_bearing` below would
    prove nothing when it lifts FORCE. So ownership is asserted, not assumed."""
    cur = store._conn.execute(
        "SELECT c.relowner::regrole::text FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %s AND c.relname = %s",
        (store._schema, table),
    )
    (owner,) = cur.fetchone()
    cur = store._conn.execute("SELECT current_user")
    (acting,) = cur.fetchone()
    store._conn.commit()

    assert owner == acting, (
        f"{table} is owned by {owner!r} but the store acts as {acting!r} -- FORCE "
        "would not be what constrains it"
    )


# =========================================================================
# 1. The policy is installed, on the container, with FORCE
# =========================================================================


@pytest.mark.parametrize("table", _OBSERVATION_TABLES)
def test_observation_tables_have_rls_enabled_and_forced(store, table: str) -> None:
    """Read straight out of `pg_class` rather than inferred from behaviour: an
    ENABLE-only setup fails this test explicitly instead of being caught (or
    missed) indirectly. `relforcerowsecurity` is the bit that actually matters,
    because the acting role owns these tables."""
    cur = store._conn.execute(
        "SELECT c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %s AND c.relname = %s",
        (store._schema, table),
    )
    row = cur.fetchone()
    store._conn.commit()

    assert row is not None, f"{table} does not exist in the container schema"
    enabled, forced = row
    assert enabled is True, (
        f"{table} on the CONTAINER has no ROW LEVEL SECURITY -- this is the gap "
        "MX-C-CONTAINER-RLS-005 exists to close"
    )
    assert forced is True, (
        f"{table} has ENABLE but not FORCE -- the owning role bypasses the policy "
        "and every isolation test below would pass for the wrong reason"
    )


# =========================================================================
# 2. Cross-tenant reads, positive controls, and the deny-all default
# =========================================================================


@pytest.mark.parametrize("table", _OBSERVATION_TABLES)
def test_cross_tenant_observation_read_is_blocked_by_the_policy(store, table: str) -> None:
    """Core proof: acting as tenant B, a raw table scan with NO WHERE clause
    returns none of tenant A's observations. Vehicle position and occupancy are
    the rows that must not leak."""
    tenant_a = _tenant("container-tenant-a")
    tenant_b = _tenant("container-tenant-b")
    _seed(store, tenant_a, vehicle_ref="a-bus")
    _seed(store, tenant_b, vehicle_ref="b-bus")

    _set_session_tenant(store, tenant_b.tenant_id)
    cur = store._conn.execute(f"SELECT observation_id, tenant_id FROM {table}")  # noqa: S608
    rows = cur.fetchall()
    store._conn.commit()

    assert {r[1] for r in rows} == {str(tenant_b.tenant_id)}, (
        f"a raw scan of {table} on the container as tenant B leaked another tenant's rows"
    )
    assert str(tenant_a.tenant_id) not in {r[1] for r in rows}


@pytest.mark.parametrize("table", _OBSERVATION_TABLES)
def test_own_tenant_observations_are_still_visible(store, table: str) -> None:
    """Positive control: the policy must not over-block. Acting as A, A's own row
    IS there -- without this, the denial above would be satisfied by an empty
    table and would prove nothing at all."""
    tenant_a = _tenant("container-tenant-a")
    tenant_b = _tenant("container-tenant-b")
    _seed(store, tenant_a, vehicle_ref="a-bus")
    _seed(store, tenant_b, vehicle_ref="b-bus")

    _set_session_tenant(store, tenant_a.tenant_id)
    cur = store._conn.execute(f"SELECT tenant_id FROM {table}")  # noqa: S608
    rows = cur.fetchall()
    store._conn.commit()

    assert len(rows) == 1, f"tenant A cannot see its own {table} row -- the policy over-blocks"
    assert rows[0][0] == str(tenant_a.tenant_id)


@pytest.mark.parametrize("table", _OBSERVATION_TABLES)
def test_reset_session_tenant_denies_all_observations(store, table: str) -> None:
    """Default-DENY, not default-allow: a forgotten GUC must hide everything
    rather than expose everything.

    AND THE EMPTY-STRING TRAP, asserted rather than assumed. It is tempting to
    write this guard (or a policy clause) as "the GUC IS NULL". That is wrong
    after a RESET: `current_setting(name, true)` returns NULL only when the GUC
    was NEVER set in the session; once it has been set and reset it returns the
    EMPTY STRING, which `IS NOT NULL` happily accepts -- the trap
    `sql/rls_postgres.sql` documents on its `model_versions` branch. This test
    pins BOTH facts: that the value here really is the empty string, and that
    deny-all holds anyway (because `tenant_id = ''` is false for any real UUID).
    Pinning them together is what stops a future policy edit from "fixing" the
    guard with an IS NOT NULL check that silently opens the door."""
    _seed(store, _tenant("container-tenant-a"), vehicle_ref="a-bus")
    _seed(store, _tenant("container-tenant-b"), vehicle_ref="b-bus")

    store._conn.execute("RESET milexium.tenant_id")
    cur = store._conn.execute(
        "SELECT current_setting('milexium.tenant_id', true) IS NULL, "
        "current_setting('milexium.tenant_id', true)"
    )
    is_null, value = cur.fetchone()
    cur = store._conn.execute(f"SELECT count(*) FROM {table}")  # noqa: S608
    (count,) = cur.fetchone()
    store._conn.commit()

    assert is_null is False and value == "", (
        "a RESET GUC is expected to read back as the EMPTY STRING, not NULL -- if "
        "this ever changes, any guard written as `IS NOT NULL` becomes load-bearing "
        "in a way it was never tested for"
    )
    assert count == 0, (
        f"a reset milexium.tenant_id exposed {count} {table} rows on the container "
        "-- the policy defaults to allow-all, which is backwards"
    )


@pytest.mark.parametrize("table", _OBSERVATION_TABLES)
def test_a_session_that_never_set_the_tenant_guc_sees_nothing(store, table: str) -> None:
    """The other half of the trap: a brand-new connection nobody ever scoped.

    Here `current_setting(..., true)` really does return NULL, and `tenant_id =
    NULL` is never true -- so an unscoped connection (a forgotten `_use_tenant`,
    a psql session someone opened with the app credential) sees nothing. Uses a
    SEPARATE connection into the same schema, because the fixture's connection
    has necessarily had the GUC set during seeding and can therefore only ever
    demonstrate the empty-string case above."""
    _seed(store, _tenant("container-tenant-a"), vehicle_ref="a-bus")

    env = _read_compose_env()
    unscoped = psycopg.connect(
        host="localhost",
        port=5433,
        dbname=env.get("POSTGRES_DB", "milexium_dev"),
        user=env.get("POSTGRES_USER", "milexium_dev"),
        password=env["POSTGRES_PASSWORD"],
    )
    try:
        unscoped.execute(
            sql.SQL("SET search_path TO {}, public").format(sql.Identifier(store._schema))
        )
        if store._acting_role is not None:
            unscoped.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(store._acting_role)))

        cur = unscoped.execute("SELECT current_setting('milexium.tenant_id', true) IS NULL")
        (is_null,) = cur.fetchone()
        cur = unscoped.execute(f"SELECT count(*) FROM {table}")  # noqa: S608
        (count,) = cur.fetchone()
        unscoped.commit()
    finally:
        unscoped.close()

    assert is_null is True, "a never-set GUC should read back as NULL"
    assert count == 0, (
        f"an unscoped connection read {count} {table} rows -- a connection nobody "
        "assigned a tenant must be able to read nobody's data"
    )


# =========================================================================
# 3. Writes: the WITH CHECK half
# =========================================================================


@pytest.mark.parametrize("table", _OBSERVATION_TABLES)
def test_observation_write_stamped_with_a_foreign_tenant_is_rejected(store, table: str) -> None:
    """Acting as an unrelated tenant, an INSERT stamped with A's tenant id is
    refused by the database, not by Python. A compromised ingest path cannot
    smuggle fabricated telemetry into another operator's evidence -- which for
    `vehicle_observations` would mean fabricated positions for someone else's
    fleet."""
    tenant_a = _tenant("container-tenant-a")
    _seed(store, tenant_a, vehicle_ref="a-bus")
    _set_session_tenant(store, new_id(TenantId))

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        store._conn.execute(
            f"INSERT INTO {table} (observation_id, tenant_id, observed_at, recorded_at) "  # noqa: S608
            "VALUES (%s, %s, '2026-07-24T16:00:00+00:00', '2026-07-24T16:00:05+00:00')",
            (str(new_id(ObservationId)), str(tenant_a.tenant_id)),
        )
    store._conn.rollback()


# =========================================================================
# 4. FORCE is what binds the owner -- shown by removing it
# =========================================================================


@pytest.mark.parametrize("table", _OBSERVATION_TABLES)
def test_force_row_level_security_is_load_bearing(store, table: str) -> None:
    """The boundary is shown COLLAPSING the instant FORCE is lifted, then
    restored. Without this, `relforcerowsecurity is True` would be a bit we
    assert because the file sets it, not because we know what it does: the acting
    role owns these tables, so ENABLE alone leaves it entirely unconstrained."""
    tenant_a = _tenant("container-tenant-a")
    _seed(store, tenant_a, vehicle_ref="a-bus")
    _set_session_tenant(store, new_id(TenantId))  # an unrelated, empty tenant

    cur = store._conn.execute(f"SELECT count(*) FROM {table}")  # noqa: S608
    assert cur.fetchone()[0] == 0, f"FORCE RLS should hide tenant A's {table} rows"

    try:
        store._conn.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")  # noqa: S608
        cur = store._conn.execute(f"SELECT count(*) FROM {table}")  # noqa: S608
        assert cur.fetchone()[0] == 1, (
            f"without FORCE the owning role bypasses RLS on {table} -- this is exactly "
            "why FORCE is required, and why an ENABLE-only setup would be a false green"
        )
    finally:
        store._conn.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")  # noqa: S608

    cur = store._conn.execute(f"SELECT count(*) FROM {table}")  # noqa: S608
    assert cur.fetchone()[0] == 0, "the boundary did not come back when FORCE was restored"
    store._conn.commit()


# =========================================================================
# 5. THE SPATIAL PATH -- the reason this store exists
# =========================================================================


def test_spatial_query_is_tenant_scoped_by_the_policy_alone(store) -> None:
    """The one that matters most.

    Two operators run the same corridor and both have a vehicle standing on the
    SAME point, so a leak here is a leak of live position data for someone else's
    fleet. The ST_DWithin predicate below is the store's real one with the
    `tenant_id = %s` filter DELETED -- the only thing left to scope it is the
    policy.

    A spatial predicate is the most plausible place for a tenant boundary to have
    a hole: it is evaluated over a GiST index by an extension's operators, and
    "the index scan sees rows the policy would have hidden" is exactly the kind of
    thing that gets assumed rather than checked. It does not -- the policy's USING
    clause is part of the scan's own qualification, so the answer is the
    intersection however the rows are reached. That is the reasoning; this test is
    the evidence, which is the point of writing it down as a test instead."""
    tenant_a = _tenant("corridor-operator-a")
    tenant_b = _tenant("corridor-operator-b")
    _seed(store, tenant_a, vehicle_ref="a-bus")
    _seed(store, tenant_b, vehicle_ref="b-bus")

    _set_session_tenant(store, tenant_a.tenant_id)
    assert _dwithin_vehicle_refs(store) == {"a-bus"}, (
        "the ST_DWithin spatial path is NOT tenant-scoped -- the geometry is a way "
        "around the policy"
    )

    # Symmetry: not an artefact of which tenant happened to be seeded first, and
    # simultaneously the positive control -- b-bus really is inside the radius.
    _set_session_tenant(store, tenant_b.tenant_id)
    assert _dwithin_vehicle_refs(store) == {"b-bus"}


def test_spatial_query_returns_nothing_to_an_unscoped_session(store) -> None:
    """Deny-all reaches the geometry too: with no tenant acting, a spatial query
    centred exactly on two known vehicles returns neither. A geospatial endpoint
    that forgot to scope its session leaks nothing rather than everything."""
    _seed(store, _tenant("corridor-operator-a"), vehicle_ref="a-bus")
    _seed(store, _tenant("corridor-operator-b"), vehicle_ref="b-bus")

    store._conn.execute("RESET milexium.tenant_id")
    assert _dwithin_vehicle_refs(store) == set()


def test_spatial_query_leaks_across_tenants_once_force_is_lifted(store) -> None:
    """FORCE is what protects the SPATIAL path specifically, not merely the plain
    scans above -- shown by removing it and watching the other operator's vehicle
    appear in the radius, then putting it back.

    This is the honest version of "the spatial path is tenant-scoped": it names
    the single setting the claim depends on, and demonstrates the leak that
    setting prevents."""
    tenant_a = _tenant("corridor-operator-a")
    tenant_b = _tenant("corridor-operator-b")
    _seed(store, tenant_a, vehicle_ref="a-bus")
    _seed(store, tenant_b, vehicle_ref="b-bus")
    _set_session_tenant(store, tenant_a.tenant_id)

    assert _dwithin_vehicle_refs(store) == {"a-bus"}

    try:
        store._conn.execute("ALTER TABLE vehicle_observations NO FORCE ROW LEVEL SECURITY")
        assert _dwithin_vehicle_refs(store) == {"a-bus", "b-bus"}, (
            "lifting FORCE did not open the spatial path -- if the geometry query "
            "were scoped by something other than the policy, this test would be "
            "silently proving nothing"
        )
    finally:
        store._conn.execute("ALTER TABLE vehicle_observations FORCE ROW LEVEL SECURITY")

    assert _dwithin_vehicle_refs(store) == {"a-bus"}


def test_the_stores_spatial_read_method_agrees_with_the_policy(store) -> None:
    """End-to-end: `observations_within()` -- the method real callers use, which
    sets the GUC itself and keeps its WHERE clause -- returns the same answer the
    policy alone gives. Two independent boundaries that agree, rather than one
    boundary and one assumption."""
    tenant_a = _tenant("corridor-operator-a")
    tenant_b = _tenant("corridor-operator-b")
    _seed(store, tenant_a, vehicle_ref="a-bus")
    _seed(store, tenant_b, vehicle_ref="b-bus")

    hits = store.observations_within(
        tenant_a.tenant_id, latitude=_BOSTON[0], longitude=_BOSTON[1], radius_meters=500
    )
    assert {h["vehicle_ref"] for h in hits} == {"a-bus"}
    assert hits[0]["distance_meters"] < 1.0  # geometry populated from lat/lon, not null
