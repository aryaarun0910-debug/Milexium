"""Adversarial fixtures for packages/connect/gtfs_realtime.py: a GTFS-Realtime
signal that is malformed, or that the operational entity family gives no honest
home, must be quarantined with a clear reason -- never silently dropped, never an
uncaught exception that kills the batch (blueprint/03-connect-and-standards.md
mapping rule 7).

This suite moved with the MX-A-OPS-ENTITY-002 re-map. Two shapes that ADR-0031's
Outcome mapping had to quarantine are NO LONGER quarantined, because the
observation entities are exactly their home: live in-transit telemetry, and a
stop_time_update that carries only its stop identity. Those are asserted to MAP
here (locking the behaviour change). What remains quarantined is genuinely
unmappable: an Alert, an entity with no stop to observe, a position with no
anchoring timestamp, a malformed epoch, and an out-of-range coordinate the entity
validator rejects.
"""

from __future__ import annotations

from packages.canonical import StopTimeObservation, VehicleObservation
from packages.connect.adapter import QuarantinedRow, parse_batch

from conformance.fixtures.builders_connect_gtfs_realtime import (
    example_alert_row,
    example_gtfs_realtime_adapter,
    example_trip_update_stop_row,
    example_vehicle_position_row,
)


def test_in_transit_vehicle_now_maps_not_quarantined() -> None:
    """Previously quarantined as 'telemetry with no canonical home'; the whole
    point of the packet is that telemetry now HAS a home."""
    adapter, _ = example_gtfs_realtime_adapter()
    row = example_vehicle_position_row(current_status="IN_TRANSIT_TO")

    result = adapter.parse(row)

    assert not result.is_quarantined
    assert isinstance(result.record, VehicleObservation)
    assert result.record.current_status == "IN_TRANSIT_TO"


def test_stopped_vehicle_missing_stop_id_still_maps() -> None:
    """A VehicleObservation is about the vehicle, not a stop, so a missing stop_id
    is not fatal -- it maps with stop_ref=None (no longer quarantined)."""
    adapter, _ = example_gtfs_realtime_adapter()
    row = example_vehicle_position_row()
    del row["stop_id"]

    result = adapter.parse(row)

    assert not result.is_quarantined
    assert isinstance(result.record, VehicleObservation)
    assert result.record.stop_ref is None


def test_vehicle_with_no_timestamp_is_quarantined() -> None:
    """observed_at must be anchored; a position with neither a vehicle nor a feed
    timestamp has no valid-time instant, so it is quarantined."""
    adapter, _ = example_gtfs_realtime_adapter()
    row = example_vehicle_position_row()
    del row["vehicle_timestamp"]
    del row["feed_timestamp"]

    result = adapter.parse(row)

    assert result.is_quarantined
    assert "observed_at" in result.quarantine.reason


def test_invalid_epoch_timestamp_is_quarantined() -> None:
    adapter, _ = example_gtfs_realtime_adapter()
    row = example_vehicle_position_row(vehicle_timestamp="not-a-number")

    result = adapter.parse(row)

    assert result.is_quarantined
    assert "not-a-number" in result.quarantine.reason


def test_out_of_range_latitude_is_quarantined_by_the_validator() -> None:
    """An out-of-[-90,90] latitude is rejected by the VehicleObservation validator;
    at the adapter boundary that surfaces as a quarantine, never a stored bad point
    (which would corrupt the PostGIS geometry derived from it)."""
    adapter, _ = example_gtfs_realtime_adapter()
    row = example_vehicle_position_row(position_latitude=200.0)

    result = adapter.parse(row)

    assert result.is_quarantined
    assert result.record is None
    assert "latitude" in result.quarantine.reason
    assert "range" in result.quarantine.reason


def test_half_present_coordinate_is_quarantined_by_the_validator() -> None:
    """A latitude without a longitude cannot form a point; the validator rejects
    the half-present pair, and the adapter quarantines it."""
    adapter, _ = example_gtfs_realtime_adapter()
    row = example_vehicle_position_row()
    del row["position_longitude"]  # latitude present, longitude gone

    result = adapter.parse(row)

    assert result.is_quarantined
    assert "together" in result.quarantine.reason


def test_alert_entity_is_quarantined_as_no_observation_home() -> None:
    adapter, _ = example_gtfs_realtime_adapter()

    result = adapter.parse(example_alert_row())

    assert result.is_quarantined
    assert "Alert" in result.quarantine.reason
    assert "no home" in result.quarantine.reason


def test_trip_update_with_no_stop_time_update_is_quarantined() -> None:
    adapter, _ = example_gtfs_realtime_adapter()
    row = example_trip_update_stop_row(_stop_time_update_present=False)

    result = adapter.parse(row)

    assert result.is_quarantined
    assert "no stop_time_update" in result.quarantine.reason


def test_empty_stop_time_update_is_quarantined() -> None:
    """A stop_time_update with no stop identity, no schedule relationship, and no
    prediction has nothing to observe -- quarantined (mapping rule 7). Contrast the
    scheduled-with-only-a-sequence case, which now maps."""
    adapter, _ = example_gtfs_realtime_adapter()
    row = example_trip_update_stop_row(arrival_delay=None, stop_schedule_relationship=None)
    for empty in ("stop_sequence", "stop_id", "arrival_time", "departure_time", "departure_delay"):
        row.pop(empty, None)

    result = adapter.parse(row)

    assert result.is_quarantined
    assert "no stop observation" in result.quarantine.reason


def test_unrecognized_kind_is_quarantined() -> None:
    adapter, _ = example_gtfs_realtime_adapter()

    result = adapter.parse({"_gtfs_rt_kind": "unknown", "entity_id": "e-1"})

    assert result.is_quarantined
    assert result.quarantine.failed_field == "_gtfs_rt_kind"


def test_row_with_no_kind_marker_is_quarantined_not_an_exception() -> None:
    adapter, _ = example_gtfs_realtime_adapter()

    result = adapter.parse({"entity_id": "e-2", "some": "payload"})

    assert result.is_quarantined
    assert result.record is None


def test_batch_with_one_bad_row_quarantines_only_that_row() -> None:
    """A malformed row (unparseable epoch) is quarantined without killing the
    batch; the good rows around it -- including an in-transit vehicle that now maps
    -- are unaffected."""
    adapter, _ = example_gtfs_realtime_adapter()
    rows = [
        example_vehicle_position_row(entity_id="a"),
        example_vehicle_position_row(entity_id="b", vehicle_timestamp="not-a-number"),
        example_trip_update_stop_row(entity_id="c", arrival_delay=5),
    ]

    results = parse_batch(adapter, rows)

    assert len(results) == 3
    assert not results[0].is_quarantined
    assert isinstance(results[0].record, VehicleObservation)
    assert results[1].is_quarantined
    assert isinstance(results[1].quarantine, QuarantinedRow)
    assert not results[2].is_quarantined
    assert isinstance(results[2].record, StopTimeObservation)
