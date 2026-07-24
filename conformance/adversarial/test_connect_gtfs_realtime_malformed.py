"""Adversarial fixtures for packages/connect/gtfs_realtime.py: a GTFS-Realtime
signal that is malformed, or that GTFS-RT's operational model gives no honest
canonical home, must be quarantined with a clear reason -- never silently
dropped, never an uncaught exception that kills the batch
(blueprint/03-connect-and-standards.md mapping rule 7). The two shapes the
packet's honest-gap analysis calls out are both covered here: live in-motion
telemetry (a VehiclePosition that is not an observed arrival), and predictive
content with no observed-Outcome home.
"""

from __future__ import annotations

from packages.connect.adapter import QuarantinedRow, parse_batch

from conformance.fixtures.builders_connect_gtfs_realtime import (
    example_alert_row,
    example_gtfs_realtime_adapter,
    example_trip_update_stop_row,
    example_vehicle_position_row,
)


def test_in_transit_vehicle_is_quarantined_as_telemetry_not_dropped() -> None:
    adapter, _ = example_gtfs_realtime_adapter()
    row = example_vehicle_position_row(current_status="IN_TRANSIT_TO")

    result = adapter.parse(row)

    assert result.is_quarantined
    assert result.record is None
    assert result.semantic_loss == ()
    assert isinstance(result.quarantine, QuarantinedRow)
    assert "IN_TRANSIT_TO" in result.quarantine.reason
    assert "telemetry" in result.quarantine.reason
    assert result.quarantine.failed_field == "current_status"
    # original row preserved verbatim for re-run.
    assert result.quarantine.raw_row["entity_id"] == "y1860"


def test_stopped_vehicle_missing_stop_id_is_quarantined() -> None:
    adapter, _ = example_gtfs_realtime_adapter()
    row = example_vehicle_position_row()
    del row["stop_id"]

    result = adapter.parse(row)

    assert result.is_quarantined
    assert "no stop_id" in result.quarantine.reason
    assert result.quarantine.failed_field == "stop_id"


def test_stopped_vehicle_with_no_timestamp_is_quarantined() -> None:
    adapter, _ = example_gtfs_realtime_adapter()
    row = example_vehicle_position_row()
    del row["vehicle_timestamp"]
    del row["feed_timestamp"]

    result = adapter.parse(row)

    assert result.is_quarantined
    assert "timestamp" in result.quarantine.reason


def test_invalid_epoch_timestamp_is_quarantined() -> None:
    adapter, _ = example_gtfs_realtime_adapter()
    row = example_vehicle_position_row(vehicle_timestamp="not-a-number")

    result = adapter.parse(row)

    assert result.is_quarantined
    assert "not-a-number" in result.quarantine.reason


def test_alert_entity_is_quarantined_as_no_canonical_home() -> None:
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


def test_scheduled_stop_with_no_time_or_delay_is_quarantined() -> None:
    """A stop_time_update that is neither SKIPPED nor carries any arrival/
    departure prediction has no outcome content to record."""

    adapter, _ = example_gtfs_realtime_adapter()
    row = example_trip_update_stop_row(
        arrival_delay=None, stop_schedule_relationship="SCHEDULED"
    )

    result = adapter.parse(row)

    assert result.is_quarantined
    assert "no outcome content" in result.quarantine.reason


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
    adapter, _ = example_gtfs_realtime_adapter()
    rows = [
        example_vehicle_position_row(entity_id="a"),
        example_vehicle_position_row(entity_id="b", current_status="IN_TRANSIT_TO"),
        example_trip_update_stop_row(entity_id="c", arrival_delay=5),
    ]

    results = parse_batch(adapter, rows)

    assert len(results) == 3
    assert not results[0].is_quarantined
    assert results[1].is_quarantined
    assert not results[2].is_quarantined
