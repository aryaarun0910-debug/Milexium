"""Conformance tests for StopTimeObservation persistence and for row-level
security on BOTH observation tables (MX-A-CANONICAL-DEBT-003).

Two distinct gaps are closed here, so this module has two clearly separated
halves that talk to two different PostgreSQL instances:

1. PERSISTENCE -- the containerized PostGIS on host port 5433.
   ADR-0035 landed `VehicleObservation` with a real spatial round-trip but gave
   `StopTimeObservation` no store method at all, leaving half the operational
   entity family unpersistable. These tests exercise
   `PostgisObservationStore.insert_stop_time_observation` /
   `.stop_time_observations` -- deliberately with NO geometry, because a
   stop-time observation has no position of its own.

2. ISOLATION -- the native PostgreSQL 17 on host port 5432.
   `sql/rls_postgres.sql` guarded every other tenant-scoped table but not the two
   observation tables, which were added to schema_v0_1.sql after it was written.
   These tests mirror conformance/adversarial/test_postgres_rls_isolation.py:
   they issue RAW SQL with NO WHERE clause after pointing the session GUC at a
   foreign tenant, so what is under test is the POLICY, not any Python filter.
   They are applied by `PostgresCanonicalStore`, which is the store that loads
   rls_postgres.sql.

Both halves skip cleanly (never fail) when their instance is absent, matching the
rest of the suite so CI stays green -- but note that a skip proves nothing, so
the packet's evidence requirement is that these RUN, not merely that they pass.

Status: Demonstrated only -- open public real-time transit data.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

psycopg = pytest.importorskip("psycopg")  # skip the whole module if absent

from packages.canonical import (  # noqa: E402
    ObservationId,
    StopTimeObservation,
    Tenant,
    TenantId,
    new_id,
)
from packages.canonical.observation_store import (  # noqa: E402
    PostgisObservationStore,
    is_reachable as postgis_is_reachable,
)
from packages.canonical.postgres_storage import (  # noqa: E402
    PostgresCanonicalStore,
    is_reachable as pg_is_reachable,
)


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _tenant(name: str) -> Tenant:
    return Tenant(tenant_id=new_id(TenantId), name=name, created_at=_utc(2026, 7, 24))


def _stop_time_obs(tenant_id: TenantId, **overrides) -> StopTimeObservation:
    fields = dict(
        observation_id=new_id(ObservationId),
        tenant_id=tenant_id,
        trip_ref="trip-44-0001",
        route_ref="44",
        stop_ref="1259",
        stop_sequence=3,
        schedule_relationship="SCHEDULED",
        predicted_arrival_at=_utc(2026, 7, 24, 16, 37, 3),
        predicted_departure_at=_utc(2026, 7, 24, 16, 37, 45),
        arrival_delay_seconds=65,
        departure_delay_seconds=-10,
        observed_at=_utc(2026, 7, 24, 16, 30, 0),
        recorded_at=_utc(2026, 7, 24, 16, 30, 5),
    )
    fields.update(overrides)
    return StopTimeObservation(**fields)


# =========================================================================
# 1. PERSISTENCE -- containerized PostGIS (5433)
# =========================================================================


@pytest.fixture
def obs_store() -> PostgisObservationStore:
    if not postgis_is_reachable():
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


def test_stop_time_observation_round_trips_with_every_field_intact(obs_store) -> None:
    """The debt this closes: the second half of the operational entity family is
    now persistable. Reconstructing the entity on read means the stored columns
    must still validate as a `StopTimeObservation`, not merely be present."""
    tenant = _tenant("stop-time-conformance")
    obs_store.create_tenant(tenant)

    obs = _stop_time_obs(tenant.tenant_id)
    obs_store.insert_stop_time_observation(obs)

    assert obs_store.stop_time_observations(tenant.tenant_id) == (obs,)


def test_predicted_and_observed_times_stay_in_separate_columns(obs_store) -> None:
    """The entity's predicted-vs-observed discipline must survive storage: a
    GTFS-Realtime *prediction* must never be read back as a record of what
    actually happened. The observed-* columns stay NULL, they are not
    back-filled from the predictions."""
    tenant = _tenant("predicted-vs-observed")
    obs_store.create_tenant(tenant)

    obs_store.insert_stop_time_observation(_stop_time_obs(tenant.tenant_id))
    (stored,) = obs_store.stop_time_observations(tenant.tenant_id)

    assert stored.predicted_arrival_at == _utc(2026, 7, 24, 16, 37, 3)
    assert stored.observed_arrival_at is None
    assert stored.observed_departure_at is None


def test_sparse_observation_round_trips_without_placeholder_values(obs_store) -> None:
    """A NO_DATA stop-time update carries almost nothing. Absent times must come
    back as None, never as an empty string or an epoch-zero placeholder."""
    tenant = _tenant("sparse")
    obs_store.create_tenant(tenant)

    sparse = _stop_time_obs(
        tenant.tenant_id,
        stop_sequence=None,
        schedule_relationship="NO_DATA",
        predicted_arrival_at=None,
        predicted_departure_at=None,
        arrival_delay_seconds=None,
        departure_delay_seconds=None,
    )
    obs_store.insert_stop_time_observation(sparse)

    (stored,) = obs_store.stop_time_observations(tenant.tenant_id)
    assert stored == sparse
    assert stored.predicted_arrival_at is None
    assert stored.stop_sequence is None


def test_observed_times_are_persisted_when_a_source_supplies_them(obs_store) -> None:
    """The observed-* fields are real columns, not decoration: a later AVL/TODS
    source populating them round-trips too."""
    tenant = _tenant("observed-source")
    obs_store.create_tenant(tenant)

    observed = _stop_time_obs(
        tenant.tenant_id,
        observed_arrival_at=_utc(2026, 7, 24, 16, 38, 8),
        observed_departure_at=_utc(2026, 7, 24, 16, 38, 50),
    )
    obs_store.insert_stop_time_observation(observed)

    (stored,) = obs_store.stop_time_observations(tenant.tenant_id)
    assert stored.observed_arrival_at == _utc(2026, 7, 24, 16, 38, 8)
    assert stored == observed


def test_stop_time_read_is_tenant_scoped(obs_store) -> None:
    """The read filters on tenant_id in SQL. Two tenants observing the SAME trip
    and stop -- which is what happens when two agencies share a corridor -- do
    not see each other's rows."""
    tenant_a = _tenant("a")
    tenant_b = _tenant("b")
    obs_store.create_tenant(tenant_a)
    obs_store.create_tenant(tenant_b)

    obs_store.insert_stop_time_observation(_stop_time_obs(tenant_a.tenant_id, stop_ref="shared"))
    obs_store.insert_stop_time_observation(_stop_time_obs(tenant_b.tenant_id, stop_ref="shared"))

    a_rows = obs_store.stop_time_observations(tenant_a.tenant_id)
    assert len(a_rows) == 1
    assert a_rows[0].tenant_id == tenant_a.tenant_id


def test_stop_time_read_returns_rows_in_valid_time_then_stop_order(obs_store) -> None:
    tenant = _tenant("ordering")
    obs_store.create_tenant(tenant)

    later = _stop_time_obs(tenant.tenant_id, stop_sequence=1, observed_at=_utc(2026, 7, 24, 17, 0))
    earlier_stop_5 = _stop_time_obs(
        tenant.tenant_id, stop_sequence=5, observed_at=_utc(2026, 7, 24, 16, 0)
    )
    earlier_stop_2 = _stop_time_obs(
        tenant.tenant_id, stop_sequence=2, observed_at=_utc(2026, 7, 24, 16, 0)
    )
    for obs in (later, earlier_stop_5, earlier_stop_2):
        obs_store.insert_stop_time_observation(obs)

    assert [o.stop_sequence for o in obs_store.stop_time_observations(tenant.tenant_id)] == [2, 5, 1]


def test_no_geometry_column_is_added_to_stop_time_observations(obs_store) -> None:
    """A stop-time observation has no position of its own, so the PostGIS
    extension must NOT have given this table a geometry column -- while the
    vehicle table, which does have a position, keeps hers. Asserting the absence
    keeps the two halves of the family from quietly converging."""
    cur = obs_store._conn.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND column_name = 'geom'",
        (obs_store._schema,),
    )
    tables_with_geometry = {row[0] for row in cur.fetchall()}
    obs_store._conn.commit()

    assert "vehicle_observations" in tables_with_geometry
    assert "stop_time_observations" not in tables_with_geometry


# =========================================================================
# 2. ISOLATION -- RLS on both observation tables, native PostgreSQL (5432)
# =========================================================================


@pytest.fixture
def rls_store() -> PostgresCanonicalStore:
    """`PostgresCanonicalStore` is the store that applies sql/rls_postgres.sql, so
    it is what proves the new observation-table policies. It never touches the
    PostGIS container."""
    if not pg_is_reachable():
        pytest.skip(
            "PostgreSQL (milexium_dev) is not reachable on this machine; "
            "skipping the observation-table RLS conformance tests"
        )
    store = PostgresCanonicalStore.connect()
    try:
        yield store
    finally:
        store.drop_schema()
        store.close()


def _set_session_tenant(store: PostgresCanonicalStore, tenant_id: object) -> None:
    """Set the RLS session key directly on the connection -- exactly what an
    attacker holding the app credential, or a plain bug, could do -- so the raw
    reads below are governed only by the policy."""
    store._conn.execute("SELECT set_config('milexium.tenant_id', %s, false)", (str(tenant_id),))


def _raw_insert_observations(store: PostgresCanonicalStore, tenant: Tenant) -> None:
    """Register `tenant` and write it one row in EACH observation table, by raw
    SQL. Neither table has a store method on `PostgresCanonicalStore`, and that is
    fine: what is under test is the database policy, not a Python code path."""
    store.create_tenant(tenant)  # also points the GUC at this tenant
    store._conn.execute(
        "INSERT INTO vehicle_observations (observation_id, tenant_id, vehicle_ref, "
        "latitude, longitude, observed_at, recorded_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (
            str(new_id(ObservationId)),
            str(tenant.tenant_id),
            "y1860",
            42.3311,
            -71.0905,
            "2026-07-24T16:37:03+00:00",
            "2026-07-24T16:37:10+00:00",
        ),
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


@pytest.mark.parametrize("table", ["vehicle_observations", "stop_time_observations"])
def test_observation_tables_have_rls_enabled_and_forced(rls_store, table: str) -> None:
    """The precondition every other test in this half rests on, asserted rather
    than assumed. ENABLE alone would be a false green: `milexium_dev` OWNS these
    tables and a table owner bypasses RLS by default (ADR-0018), so `relforcerowsecurity`
    is the bit that actually matters."""
    cur = rls_store._conn.execute(
        "SELECT c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %s AND c.relname = %s",
        (rls_store._schema, table),
    )
    enabled, forced = cur.fetchone()
    rls_store._conn.commit()

    assert enabled is True, f"{table} does not have ROW LEVEL SECURITY enabled"
    assert forced is True, (
        f"{table} has ENABLE but not FORCE -- the owning role bypasses the policy "
        "and every isolation test below would pass for the wrong reason"
    )


@pytest.mark.parametrize("table", ["vehicle_observations", "stop_time_observations"])
def test_cross_tenant_observation_read_is_blocked_by_the_policy(rls_store, table: str) -> None:
    """Core proof: acting as tenant B, a raw table scan with NO WHERE clause
    returns zero of tenant A's observations. Vehicle position is the most
    sensitive operational data in the schema, so this is the row that must not
    leak."""
    tenant_a = _tenant("obs-tenant-a")
    tenant_b = _tenant("obs-tenant-b")
    _raw_insert_observations(rls_store, tenant_a)
    _raw_insert_observations(rls_store, tenant_b)

    _set_session_tenant(rls_store, tenant_b.tenant_id)
    cur = rls_store._conn.execute(f"SELECT observation_id, tenant_id FROM {table}")
    rows = cur.fetchall()
    rls_store._conn.commit()

    assert {r[1] for r in rows} == {str(tenant_b.tenant_id)}, (
        f"a raw scan of {table} as tenant B leaked another tenant's rows"
    )
    assert str(tenant_a.tenant_id) not in {r[1] for r in rows}


@pytest.mark.parametrize("table", ["vehicle_observations", "stop_time_observations"])
def test_own_tenant_observations_are_still_visible(rls_store, table: str) -> None:
    """Positive control: the policy must not over-block. Acting as A, A's own
    observation is there -- otherwise the test above would pass on an empty
    table and prove nothing."""
    tenant_a = _tenant("obs-tenant-a")
    _raw_insert_observations(rls_store, tenant_a)

    _set_session_tenant(rls_store, tenant_a.tenant_id)
    cur = rls_store._conn.execute(f"SELECT count(*) FROM {table}")
    (count,) = cur.fetchone()
    rls_store._conn.commit()

    assert count == 1


@pytest.mark.parametrize("table", ["vehicle_observations", "stop_time_observations"])
def test_unset_session_tenant_denies_all_observations(rls_store, table: str) -> None:
    """Default-DENY, not default-allow. With no tenant named,
    `current_setting(..., true)` yields NULL and `tenant_id = NULL` is never
    true, so a forgotten GUC hides everything rather than exposing everything --
    the failure mode that matters."""
    _raw_insert_observations(rls_store, _tenant("obs-tenant-a"))
    _raw_insert_observations(rls_store, _tenant("obs-tenant-b"))

    rls_store._conn.execute("RESET milexium.tenant_id")
    cur = rls_store._conn.execute(f"SELECT count(*) FROM {table}")
    (count,) = cur.fetchone()
    rls_store._conn.commit()

    assert count == 0, (
        f"an unset milexium.tenant_id exposed {count} {table} rows -- the policy "
        "defaults to allow-all, which is backwards"
    )


@pytest.mark.parametrize("table", ["vehicle_observations", "stop_time_observations"])
def test_observation_write_stamped_with_a_foreign_tenant_is_rejected(rls_store, table: str) -> None:
    """The WITH CHECK half: acting as B, an INSERT stamped with A's tenant id is
    refused at the database layer. A compromised ingest path cannot smuggle
    fabricated telemetry into another operator's evidence."""
    tenant_a = _tenant("obs-tenant-a")
    _raw_insert_observations(rls_store, tenant_a)
    _set_session_tenant(rls_store, new_id(TenantId))

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        rls_store._conn.execute(
            f"INSERT INTO {table} (observation_id, tenant_id, observed_at, recorded_at) "
            "VALUES (%s, %s, '2026-07-24T16:00:00+00:00', '2026-07-24T16:00:05+00:00')",
            (str(new_id(ObservationId)), str(tenant_a.tenant_id)),
        )
    rls_store._conn.rollback()


@pytest.mark.parametrize("table", ["vehicle_observations", "stop_time_observations"])
def test_force_row_level_security_is_load_bearing_on_observations(rls_store, table: str) -> None:
    """Proves FORCE -- not ENABLE alone -- is what binds the OWNING role on these
    two tables specifically, mirroring the same proof for `decision_events` in
    conformance/adversarial/test_postgres_rls_isolation.py. The boundary is shown
    collapsing the instant FORCE is lifted, then restored."""
    tenant_a = _tenant("obs-tenant-a")
    _raw_insert_observations(rls_store, tenant_a)
    _set_session_tenant(rls_store, new_id(TenantId))  # an empty, unrelated tenant

    cur = rls_store._conn.execute(f"SELECT count(*) FROM {table}")
    assert cur.fetchone()[0] == 0, f"FORCE RLS should hide tenant A's {table} rows"

    rls_store._conn.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    cur = rls_store._conn.execute(f"SELECT count(*) FROM {table}")
    assert cur.fetchone()[0] == 1, (
        f"without FORCE the owning role bypasses RLS on {table} -- this is exactly "
        "why FORCE is required, and why an ENABLE-only setup would be a false green"
    )

    rls_store._conn.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    cur = rls_store._conn.execute(f"SELECT count(*) FROM {table}")
    assert cur.fetchone()[0] == 0
    rls_store._conn.commit()
