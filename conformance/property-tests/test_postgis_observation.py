"""PostGIS conformance: a real spatial round-trip against the running PostGIS
container (infra/compose, host port 5433), proving the operational-entity family's
geometry path works end-to-end -- a VehicleObservation's plain lat/lon REAL columns
(the portable base schema) are derived into a geometry(Point,4326) by the
Postgres-only postgis_postgres.sql extension, and a spatial query (ST_DWithin)
reads the observation back.

Skips cleanly when `psycopg` isn't installed or the PostGIS container isn't
reachable (mirroring conformance/property-tests/test_object_store.py), so the suite
stays green on CI and on a machine without the dev stack up.

Status: Demonstrated only -- open public real-time transit data.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

psycopg = pytest.importorskip("psycopg")  # noqa: F841 -- skip whole module if absent

from packages.canonical import (  # noqa: E402
    ObservationId,
    Tenant,
    TenantId,
    VehicleObservation,
    new_id,
)
from packages.canonical.observation_store import (  # noqa: E402
    PostgisObservationStore,
    is_reachable,
)

# A point in Boston (an MBTA route-44 stop) and a far-away point in London.
_BOSTON = (42.3311, -71.0905)
_LONDON = (51.5074, -0.1278)


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


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


def _observation(tenant_id: TenantId, lat: float, lon: float, ref: str) -> VehicleObservation:
    return VehicleObservation(
        observation_id=new_id(ObservationId),
        tenant_id=tenant_id,
        vehicle_ref=ref,
        current_status="STOPPED_AT",
        latitude=lat,
        longitude=lon,
        observed_at=_utc(2026, 7, 24, 16, 37, 3),
        recorded_at=_utc(2026, 7, 24, 9, 0),
    )


def test_geometry_round_trip_spatial_query_returns_the_observation(store) -> None:
    tenant = Tenant(tenant_id=new_id(TenantId), name="postgis-conformance", created_at=_utc(2026, 7, 24))
    store.create_tenant(tenant)

    near = _observation(tenant.tenant_id, *_BOSTON, ref="y-near")
    far = _observation(tenant.tenant_id, *_LONDON, ref="y-far")
    store.insert_vehicle_observation(near)
    store.insert_vehicle_observation(far)

    # Within 500 m of the Boston point: only the near observation, its geometry
    # (derived from the stored lat/lon) essentially coincident with the query point.
    hits = store.observations_within(
        tenant.tenant_id, latitude=_BOSTON[0], longitude=_BOSTON[1], radius_meters=500
    )
    refs = {h["vehicle_ref"] for h in hits}
    assert refs == {"y-near"}
    assert hits[0]["distance_meters"] < 1.0  # geometry populated from lat/lon, not null

    # The London observation is ~5000 km away -> excluded from the Boston query,
    # but found by a query centred on London.
    london_hits = store.observations_within(
        tenant.tenant_id, latitude=_LONDON[0], longitude=_LONDON[1], radius_meters=500
    )
    assert {h["vehicle_ref"] for h in london_hits} == {"y-far"}


def test_spatial_query_is_tenant_scoped(store) -> None:
    tenant_a = Tenant(tenant_id=new_id(TenantId), name="a", created_at=_utc(2026, 7, 24))
    tenant_b = Tenant(tenant_id=new_id(TenantId), name="b", created_at=_utc(2026, 7, 24))
    store.create_tenant(tenant_a)
    store.create_tenant(tenant_b)

    store.insert_vehicle_observation(_observation(tenant_a.tenant_id, *_BOSTON, ref="a-bus"))
    store.insert_vehicle_observation(_observation(tenant_b.tenant_id, *_BOSTON, ref="b-bus"))

    hits = store.observations_within(
        tenant_a.tenant_id, latitude=_BOSTON[0], longitude=_BOSTON[1], radius_meters=500
    )
    assert {h["vehicle_ref"] for h in hits} == {"a-bus"}
