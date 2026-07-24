"""Property/conformance tests for the request-INDEPENDENT operational entity family
(VehicleObservation + StopTimeObservation) added in MX-A-OPS-ENTITY-002 to close the
ADR-0031 gap, and for the GtfsRealtimeAdapter re-map onto them.

Two things are proven here:

1. Entity validation: the observation entities are frozen, forbid extra fields,
   reject out-of-range / half-present latitude/longitude (the validator that guards
   the PostGIS geometry derived from those columns), and require UTC times.
2. Adapter re-map correctness on plain-dict fixtures (no protobuf needed) and on the
   real acquired samples if present: GTFS-RT vehicle positions and trip stop-time
   updates now map to observations with their operational context intact, no
   synthetic request id, and only genuinely-homeless detail as semantic loss.

Status: Demonstrated only -- open public real-time transit data.
"""

from __future__ import annotations

import glob
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from packages.canonical import (
    ObservationId,
    StopTimeObservation,
    TenantId,
    VehicleObservation,
    new_id,
)
from packages.connect.gtfs_realtime import BINDINGS_AVAILABLE, read_gtfs_realtime_feed

from conformance.fixtures.builders_connect_gtfs_realtime import (
    example_gtfs_realtime_adapter,
    example_trip_update_stop_row,
    example_vehicle_position_row,
)

STANDARDS_DIR = Path(__file__).parents[2] / "data" / "standards"


def _vehicle_obs(**overrides) -> VehicleObservation:
    fields = dict(
        observation_id=new_id(ObservationId),
        tenant_id=new_id(TenantId),
        vehicle_ref="y1860",
        latitude=42.3311,
        longitude=-71.0905,
        current_status="STOPPED_AT",
        observed_at=datetime(2023, 7, 22, 5, 46, 45, tzinfo=timezone.utc),
        recorded_at=datetime(2026, 7, 24, 9, 0, tzinfo=timezone.utc),
    )
    fields.update(overrides)
    return VehicleObservation(**fields)


def _stop_time_obs(**overrides) -> StopTimeObservation:
    fields = dict(
        observation_id=new_id(ObservationId),
        tenant_id=new_id(TenantId),
        trip_ref="trip-1",
        stop_sequence=3,
        schedule_relationship="SCHEDULED",
        observed_at=datetime(2010, 9, 14, 12, 24, 28, tzinfo=timezone.utc),
        recorded_at=datetime(2026, 7, 24, 9, 0, tzinfo=timezone.utc),
    )
    fields.update(overrides)
    return StopTimeObservation(**fields)


# -- entity validation ------------------------------------------------------


def test_valid_vehicle_observation_constructs_and_is_request_independent() -> None:
    obs = _vehicle_obs()
    assert obs.observation_id  # its own key
    # There is deliberately no request_id / rider field to set.
    assert "request_id" not in obs.model_dump()


def test_valid_stop_time_observation_constructs() -> None:
    obs = _stop_time_obs(arrival_delay_seconds=5)
    assert obs.arrival_delay_seconds == 5
    assert obs.observed_arrival_at is None


@pytest.mark.parametrize("bad_lat", [90.001, -90.001, 200.0, -200.0])
def test_out_of_range_latitude_is_rejected(bad_lat: float) -> None:
    with pytest.raises(ValidationError, match="latitude"):
        _vehicle_obs(latitude=bad_lat, longitude=0.0)


@pytest.mark.parametrize("bad_lon", [180.001, -180.001, 360.0])
def test_out_of_range_longitude_is_rejected(bad_lon: float) -> None:
    with pytest.raises(ValidationError, match="longitude"):
        _vehicle_obs(latitude=0.0, longitude=bad_lon)


def test_boundary_coordinates_are_accepted() -> None:
    assert _vehicle_obs(latitude=90.0, longitude=180.0).latitude == 90.0
    assert _vehicle_obs(latitude=-90.0, longitude=-180.0).longitude == -180.0


def test_latitude_without_longitude_is_rejected() -> None:
    with pytest.raises(ValidationError, match="together"):
        _vehicle_obs(latitude=42.0, longitude=None)


def test_longitude_without_latitude_is_rejected() -> None:
    with pytest.raises(ValidationError, match="together"):
        _vehicle_obs(latitude=None, longitude=-71.0)


def test_absent_position_is_allowed() -> None:
    obs = _vehicle_obs(latitude=None, longitude=None)
    assert obs.latitude is None and obs.longitude is None


def test_negative_occupancy_percentage_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _vehicle_obs(occupancy_percentage=-1)


def test_negative_stop_sequence_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _stop_time_obs(stop_sequence=-1)


def test_naive_observed_at_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _vehicle_obs(observed_at=datetime(2023, 7, 22, 5, 46, 45))  # no tzinfo


def test_observations_are_frozen_and_forbid_extra_fields() -> None:
    obs = _vehicle_obs()
    with pytest.raises(ValidationError):
        VehicleObservation(request_id="nope", **obs.model_dump())  # extra field
    with pytest.raises(ValidationError):
        obs.latitude = 0.0  # frozen


# -- adapter re-map correctness (dict fixtures) -----------------------------


def test_adapter_maps_vehicle_position_with_full_context() -> None:
    adapter, tenant_id = example_gtfs_realtime_adapter()
    result = adapter.parse(example_vehicle_position_row())

    assert not result.is_quarantined
    obs = result.record
    assert isinstance(obs, VehicleObservation)
    assert obs.tenant_id == tenant_id
    assert (obs.stop_ref, obs.route_ref, obs.vehicle_ref) == ("1259", "44", "y1860")
    assert (obs.latitude, obs.longitude) == (42.3311, -71.0905)
    assert obs.occupancy_status == "MANY_SEATS_AVAILABLE"


def test_remap_drops_the_synthetic_request_loss_and_shrinks_loss() -> None:
    """The ADR-0031 synthetic-request coercion is gone, and the residual loss is
    only a handful of genuinely-homeless fields (vs the Outcome era's ~18)."""
    adapter, _ = example_gtfs_realtime_adapter()
    result = adapter.parse(example_vehicle_position_row())

    assert not any("rider request" in loss.reason for loss in result.semantic_loss)
    assert all(loss.disposition in ("dropped", "unmapped_extension") for loss in result.semantic_loss)
    assert len(result.semantic_loss) <= 8


def test_adapter_maps_trip_update_stop_to_stop_time_observation() -> None:
    adapter, _ = example_gtfs_realtime_adapter()
    result = adapter.parse(example_trip_update_stop_row(arrival_delay=5))

    obs = result.record
    assert isinstance(obs, StopTimeObservation)
    assert obs.arrival_delay_seconds == 5
    assert obs.stop_sequence == 3


# -- adapter re-map correctness (real acquired sample, if present) ----------


def test_real_vehicle_sample_maps_every_position_to_an_observation() -> None:
    if not BINDINGS_AVAILABLE:
        pytest.skip("gtfs-realtime-bindings not installed")
    pb_samples = sorted(glob.glob(str(STANDARDS_DIR / "gtfs-rt-*.pb")))
    if not pb_samples:
        pytest.skip("no gtfs-rt-*.pb VehiclePositions sample present")

    adapter, _ = example_gtfs_realtime_adapter()
    mapped = quarantined = 0
    loss_total = 0
    for sample in pb_samples:
        for result in (adapter.parse(row) for row in read_gtfs_realtime_feed(sample)):
            if result.is_quarantined:
                quarantined += 1
                continue
            assert isinstance(result.record, VehicleObservation)
            mapped += 1
            loss_total += len(result.semantic_loss)
            assert not any("rider request" in loss.reason for loss in result.semantic_loss)

    assert mapped > 0
    # Every vehicle position maps now (no STOPPED_AT gate) -> nothing quarantined.
    assert quarantined == 0
    # Residual loss per record is small -- the operational context has homes.
    assert loss_total / mapped < 8
