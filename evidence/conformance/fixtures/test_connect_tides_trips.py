"""Fixture-level conformance for app/connect/tides_trips.py: a TIDES
trips_performed row maps to a schema-valid ServiceRequest, and every source
field ServiceRequest v0.1 has no home for -- including the structural gaps
(no rider identity, no mobility-device field, no request timestamp) -- is
reported as semantic loss rather than silently discarded
(blueprint/03-connect-and-standards.md, "no adapter leaks vendor-specific
meanings into Core... without recording"). Status: Demonstrated only -- TIDES
is an open-spec fixture, not consented paratransit operator data (see
app/connect/tides_trips.py docstring).
"""

from __future__ import annotations

import csv
from pathlib import Path

from app.canonical import ServiceRequest, ServiceRequestState
from app.verify import verify_against_schema

from conformance.fixtures.builders_connect_tides import (
    TIDES_TRIPS_PERFORMED_COLUMNS,
    example_tides_adapter,
    example_tides_row,
)

STANDARDS_DIR = Path(__file__).parents[3] / "data" / "standards"


def test_valid_trip_row_maps_to_a_schema_valid_service_request() -> None:
    adapter, tenant_id = example_tides_adapter()
    result = adapter.parse(example_tides_row())

    assert not result.is_quarantined
    assert result.quarantine is None
    request = result.record
    assert isinstance(request, ServiceRequest)
    assert request.tenant_id == tenant_id
    assert request.status == ServiceRequestState.REQUESTED
    assert request.meta.version == 1
    assert not request.meta.is_correction()
    assert request.pickup_zone == "STOP-114"
    assert request.dropoff_zone == "STOP-256"
    assert request.mobility_device is None  # TIDES trips_performed has no such field
    # requested_at is the service_date day-anchor (midnight UTC), NOT a real request time.
    assert request.times.requested_at.isoformat() == "2025-07-01T00:00:00+00:00"
    assert request.times.scheduled_pickup_at.isoformat() == "2025-07-01T08:15:00+00:00"
    assert request.times.actual_pickup_at.isoformat() == "2025-07-01T08:19:00+00:00"
    assert request.times.negotiated_window_start is None
    assert request.rider_ref.startswith("tides-no-rider-")

    # The mandatory requested_at must not sort after the scheduled/actual times
    # -- the ordering the service_date choice was made to preserve.
    assert request.times.requested_at <= request.times.scheduled_pickup_at
    assert request.times.requested_at <= request.times.actual_pickup_at

    errors = verify_against_schema(request.model_dump(mode="json"), ServiceRequest)
    assert errors == []


def test_service_date_to_requested_at_is_recorded_as_a_coerced_semantic_loss() -> None:
    """The headline mapping judgment: TIDES has no request timestamp, so
    service_date fills the mandatory requested_at as an explicit placeholder --
    it must be recorded as a coerced loss on every successful mapping, never a
    silent guess."""

    adapter, _ = example_tides_adapter()
    result = adapter.parse(example_tides_row())

    lost = [loss for loss in result.semantic_loss if loss.source_field == "service_date"]
    assert len(lost) == 1
    assert lost[0].disposition == "coerced"
    assert lost[0].source_value == "2025-07-01"


def test_timestamp_mappings_are_recorded_as_coerced_losses() -> None:
    adapter, _ = example_tides_adapter()
    result = adapter.parse(example_tides_row())

    losses = {loss.source_field: loss for loss in result.semantic_loss}
    assert losses["schedule_trip_start"].disposition == "coerced"
    assert losses["actual_trip_start"].disposition == "coerced"


def test_missing_rider_identity_and_mobility_device_are_recorded_as_dropped() -> None:
    """TIDES trips_performed has no rider identifier and no mobility-device
    field; both structural gaps must surface as recorded dropped losses, not
    unremarked Nones on the record."""

    adapter, _ = example_tides_adapter()
    result = adapter.parse(example_tides_row())

    rider = [loss for loss in result.semantic_loss if loss.source_field == "<no rider/passenger identifier column>"]
    assert len(rider) == 1
    assert rider[0].disposition == "dropped"
    assert rider[0].source_value is None

    mobility = [loss for loss in result.semantic_loss if loss.source_field == "<no mobility-device column>"]
    assert len(mobility) == 1
    assert mobility[0].disposition == "dropped"


def test_rider_ref_is_never_a_stable_identity() -> None:
    """Two different TIDES trips must not collide onto the same rider_ref --
    the placeholder is per-row, never a joinable identity."""

    adapter, _ = example_tides_adapter()
    result_a = adapter.parse(example_tides_row())
    result_b = adapter.parse(example_tides_row(trip_id_performed="TP-999", trip_start_stop_id="STOP-9"))

    assert result_a.record.rider_ref != result_b.record.rider_ref


def test_known_but_uncovered_source_fields_are_recorded_as_semantic_loss() -> None:
    """route_id/vehicle_id/block_id/shape_id/trip_type/schedule_relationship
    etc. are real, meaningful TIDES columns ServiceRequest v0.1 has no field
    for -- they must be reported as dropped, not silently discarded."""

    adapter, _ = example_tides_adapter()
    result = adapter.parse(example_tides_row())

    lost = {loss.source_field: loss for loss in result.semantic_loss}
    for column in (
        "date",
        "trip_id_performed",
        "vehicle_id",
        "trip_id_scheduled",
        "route_id",
        "route_type",
        "shape_id",
        "direction_id",
        "operator_id",
        "block_id",
        "schedule_trip_end",
        "actual_trip_end",
        "trip_type",
        "schedule_relationship",
    ):
        assert lost[column].disposition == "dropped", column
    assert lost["route_id"].source_value == "DR-FLEX-1"
    assert lost["vehicle_id"].source_value == "VH-07"


def test_extra_vendor_field_is_recorded_as_an_unmapped_extension() -> None:
    """A field outside the documented TIDES trips_performed schema must surface
    with disposition 'unmapped_extension', not vanish or raise."""

    adapter, _ = example_tides_adapter()
    result = adapter.parse(example_tides_row(fare_paid="2.50"))

    assert not result.is_quarantined
    extension_losses = [loss for loss in result.semantic_loss if loss.disposition == "unmapped_extension"]
    assert len(extension_losses) == 1
    assert extension_losses[0].source_field == "fare_paid"
    assert extension_losses[0].source_value == "2.50"


def test_row_without_optional_timestamps_still_maps() -> None:
    """schedule_trip_start/actual_trip_start are optional (e.g. an added/
    unscheduled trip); their absence must not block the mapping or its
    schema-validity, and must not emit a coerced timestamp loss."""

    adapter, _ = example_tides_adapter()
    result = adapter.parse(example_tides_row(schedule_trip_start="", actual_trip_start=""))

    assert not result.is_quarantined
    request = result.record
    assert request.times.scheduled_pickup_at is None
    assert request.times.actual_pickup_at is None
    fields = {loss.source_field for loss in result.semantic_loss}
    assert "schedule_trip_start" not in fields
    assert "actual_trip_start" not in fields

    errors = verify_against_schema(request.model_dump(mode="json"), ServiceRequest)
    assert errors == []


def test_adapter_expected_columns_match_the_real_tides_header_on_disk() -> None:
    """Cross-check the adapter's expected column set against the real TIDES
    trips_performed header acquired at data/standards/tides-sample.*.csv.
    Skips cleanly if the sample file is not present in this environment."""

    import glob

    import pytest

    files = sorted(glob.glob(str(STANDARDS_DIR / "tides-sample.*.csv")))
    if not files:
        pytest.skip(f"no tides-sample.*.csv found under {STANDARDS_DIR}")

    with open(files[0], newline="", encoding="utf-8") as handle:
        header = next(csv.reader(handle))

    assert tuple(header) == TIDES_TRIPS_PERFORMED_COLUMNS

    # Every column the adapter names (required + mapped-optional + explicitly
    # dropped) must be a real TIDES column, and every real TIDES column must be
    # accounted for by the adapter -- nothing silently unhandled.
    from app.connect.tides_trips import _KNOWN_COLUMNS

    assert _KNOWN_COLUMNS == frozenset(header)
