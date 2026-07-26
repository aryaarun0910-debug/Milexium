"""Adversarial fixtures for app/connect/tides_trips.py: malformed or
incomplete TIDES trips_performed rows must be quarantined with a clear reason
-- never silently dropped, never an uncaught exception that kills the batch
(blueprint/03-connect-and-standards.md mapping rule 7: "quarantine impossible
or policy-sensitive records rather than guessing"). These are realistic TIDES
conditions: a performed-trip row missing a boundary stop id, or a service_date/
timestamp cell that failed to serialize cleanly on export.
"""

from __future__ import annotations

from app.connect.adapter import QuarantinedRow, parse_batch

from conformance.fixtures.builders_connect_tides import example_tides_adapter, example_tides_row


def test_row_missing_trip_start_stop_id_is_quarantined_not_dropped() -> None:
    adapter, _ = example_tides_adapter()
    row = example_tides_row(trip_start_stop_id="")

    result = adapter.parse(row)

    assert result.is_quarantined
    assert result.record is None
    assert result.semantic_loss == ()
    assert isinstance(result.quarantine, QuarantinedRow)
    assert "trip_start_stop_id" in result.quarantine.reason
    assert result.quarantine.failed_field == "trip_start_stop_id"
    assert result.quarantine.raw_row["trip_end_stop_id"] == "STOP-256"  # original row preserved


def test_row_missing_trip_end_stop_id_is_quarantined() -> None:
    adapter, _ = example_tides_adapter()
    result = adapter.parse(example_tides_row(trip_end_stop_id=None))

    assert result.is_quarantined
    assert "trip_end_stop_id" in result.quarantine.reason
    assert result.quarantine.failed_field == "trip_end_stop_id"


def test_row_missing_service_date_is_quarantined_because_requested_at_has_no_anchor() -> None:
    """service_date is the only field filling the mandatory requested_at; with
    it absent there is no honest anchor at all, so the row is quarantined
    rather than fabricating a request time."""

    adapter, _ = example_tides_adapter()
    result = adapter.parse(example_tides_row(service_date=""))

    assert result.is_quarantined
    assert "service_date" in result.quarantine.reason
    assert result.quarantine.failed_field == "service_date"


def test_unparseable_service_date_is_quarantined_with_a_clear_reason() -> None:
    adapter, _ = example_tides_adapter()
    result = adapter.parse(example_tides_row(service_date="not-a-date"))

    assert result.is_quarantined
    assert "service_date" in result.quarantine.reason
    assert "not-a-date" in result.quarantine.reason


def test_unparseable_schedule_trip_start_timestamp_is_quarantined() -> None:
    adapter, _ = example_tides_adapter()
    result = adapter.parse(example_tides_row(schedule_trip_start="08:15 yesterday"))

    assert result.is_quarantined
    assert "schedule_trip_start" in result.quarantine.reason
    assert "08:15 yesterday" in result.quarantine.reason


def test_unparseable_actual_trip_start_timestamp_is_quarantined() -> None:
    adapter, _ = example_tides_adapter()
    result = adapter.parse(example_tides_row(actual_trip_start="garbage"))

    assert result.is_quarantined
    assert "actual_trip_start" in result.quarantine.reason


def test_batch_with_one_bad_row_quarantines_only_that_row() -> None:
    adapter, _ = example_tides_adapter()
    rows = [
        example_tides_row(trip_id_performed="TP-1"),
        example_tides_row(trip_id_performed="TP-2", service_date=""),
        example_tides_row(trip_id_performed="TP-3", trip_start_stop_id="STOP-3"),
    ]

    results = parse_batch(adapter, rows)

    assert len(results) == 3
    assert not results[0].is_quarantined
    assert results[1].is_quarantined
    assert not results[2].is_quarantined
    assert results[0].record.rider_ref != results[2].record.rider_ref
