"""Fixture-level conformance for packages/connect/gtfs_realtime.py: a well-formed
GTFS-Realtime operational signal now maps to a schema-valid, request-INDEPENDENT
canonical observation -- a ``VehicleObservation`` or a ``StopTimeObservation`` --
with the operational context (position, occupancy, status, stop/route/trip refs,
predicted times, delays) that ADR-0031's Outcome squash had no home for now landing
in real fields, and only genuinely-homeless detail recorded as semantic loss
(blueprint/03-connect-and-standards.md).

This suite moved with the re-map in MX-A-OPS-ENTITY-002: it previously asserted the
Outcome mapping (and the synthetic request_id that was ADR-0031's headline gap);
that gap is closed, so it now asserts the observation mapping and that NO synthetic
request id is minted.

Status: Demonstrated only -- open public real-time transit data (the Apache-2.0
GTFS-Realtime spec example and an open MBTA feed snapshot), not consented operator
data.
"""

from __future__ import annotations

import glob
from datetime import datetime, timezone
from pathlib import Path

from packages.canonical import StopTimeObservation, VehicleObservation
from packages.connect.gtfs_realtime import BINDINGS_AVAILABLE, read_gtfs_realtime_feed
from packages.verify import verify_against_schema

from conformance.fixtures.builders_connect_gtfs_realtime import (
    example_gtfs_realtime_adapter,
    example_trip_update_stop_row,
    example_vehicle_position_row,
)

STANDARDS_DIR = Path(__file__).parents[2] / "data" / "standards"


def _utc_from_epoch(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def test_stopped_vehicle_maps_to_a_schema_valid_observation() -> None:
    adapter, tenant_id = example_gtfs_realtime_adapter()
    result = adapter.parse(example_vehicle_position_row())

    assert not result.is_quarantined
    assert result.quarantine is None
    obs = result.record
    assert isinstance(obs, VehicleObservation)
    assert obs.tenant_id == tenant_id
    # The operational context now has REAL homes (ADR-0031 gap closed):
    assert obs.current_status == "STOPPED_AT"
    assert obs.stop_ref == "1259"
    assert obs.route_ref == "44"
    assert obs.vehicle_ref == "y1860"
    assert obs.trip_ref == "76573594"
    assert obs.latitude == 42.3311
    assert obs.longitude == -71.0905
    assert obs.occupancy_status == "MANY_SEATS_AVAILABLE"
    # observed_at is valid time from the vehicle's epoch; recorded_at is txn time.
    assert obs.observed_at == _utc_from_epoch(1690004805)
    assert obs.recorded_at == datetime(2026, 7, 24, 9, 0, tzinfo=timezone.utc)

    errors = verify_against_schema(obs.model_dump(mode="json"), VehicleObservation)
    assert errors == []


def test_in_transit_vehicle_now_maps_too_no_longer_quarantined() -> None:
    """The headline behaviour change: an in-transit vehicle is exactly what a
    telemetry entity records, so it is no longer squashed/quarantined -- it maps
    to a VehicleObservation carrying its live position and status."""
    adapter, _ = example_gtfs_realtime_adapter()
    result = adapter.parse(example_vehicle_position_row(current_status="IN_TRANSIT_TO"))

    assert not result.is_quarantined
    obs = result.record
    assert isinstance(obs, VehicleObservation)
    assert obs.current_status == "IN_TRANSIT_TO"
    assert obs.latitude == 42.3311


def test_no_synthetic_request_id_is_minted_the_gap_is_closed() -> None:
    """ADR-0031's core gap: Outcome forced a synthetic request_id referencing no
    ServiceRequest, recorded as a coerced loss on every row. The observation keys
    on its OWN observation_id, so that loss note is gone entirely."""
    adapter, _ = example_gtfs_realtime_adapter()
    result = adapter.parse(example_vehicle_position_row())

    assert result.record.observation_id  # a real, self-owned key
    synthetic = [
        loss
        for loss in result.semantic_loss
        if "rider request" in loss.reason or "request_id" in loss.source_field
    ]
    assert synthetic == []


def test_vehicle_falls_back_to_feed_timestamp_when_vehicle_timestamp_absent() -> None:
    adapter, _ = example_gtfs_realtime_adapter()
    row = example_vehicle_position_row()
    del row["vehicle_timestamp"]

    result = adapter.parse(row)

    assert not result.is_quarantined
    assert result.record.observed_at == _utc_from_epoch(1690004800)


def test_vehicle_residual_loss_is_only_genuinely_homeless_detail() -> None:
    """Position/occupancy/stop/route now map, so they are NOT loss. Only genuinely
    homeless detail (direction, service date, label, current_stop_sequence) is."""
    adapter, _ = example_gtfs_realtime_adapter()
    result = adapter.parse(example_vehicle_position_row())

    lost = {loss.source_field: loss for loss in result.semantic_loss}
    # These have homes now -> must NOT appear as loss:
    for mapped_field in ("stop_id", "position_latitude", "occupancy_status", "route_id"):
        assert mapped_field not in lost
    # These remain homeless residual -> recorded as dropped:
    assert lost["direction_id"].disposition == "dropped"
    assert lost["trip_start_date"].disposition == "dropped"


def test_trip_update_delay_maps_to_a_schema_valid_stop_time_observation() -> None:
    adapter, _ = example_gtfs_realtime_adapter()
    result = adapter.parse(example_trip_update_stop_row(arrival_delay=5))

    assert not result.is_quarantined
    obs = result.record
    assert isinstance(obs, StopTimeObservation)
    # The delay now has a real home (no |delay|<=60s on_time coercion any more):
    assert obs.arrival_delay_seconds == 5
    assert obs.stop_sequence == 3
    assert obs.trip_ref == "trip-1"
    # GTFS-RT carries predictions, so observed times stay None.
    assert obs.observed_arrival_at is None

    errors = verify_against_schema(obs.model_dump(mode="json"), StopTimeObservation)
    assert errors == []


def test_predicted_arrival_time_maps_to_the_predicted_field() -> None:
    adapter, _ = example_gtfs_realtime_adapter()
    result = adapter.parse(
        example_trip_update_stop_row(arrival_time=1690004900, arrival_delay=30)
    )

    obs = result.record
    # A predicted arrival now has a home -- predicted_arrival_at, NOT dropped as
    # it was under Outcome (which had no predicted-time field).
    assert obs.predicted_arrival_at == _utc_from_epoch(1690004900)
    assert obs.observed_arrival_at is None
    assert obs.arrival_delay_seconds == 30


def test_skipped_stop_maps_to_schedule_relationship() -> None:
    """SKIPPED is now just the stop's schedule_relationship on the observation --
    no served=False coercion onto a rider-request record."""
    adapter, _ = example_gtfs_realtime_adapter()
    result = adapter.parse(
        example_trip_update_stop_row(
            stop_schedule_relationship="SKIPPED", arrival_delay=None
        )
    )

    assert not result.is_quarantined
    obs = result.record
    assert isinstance(obs, StopTimeObservation)
    assert obs.schedule_relationship == "SKIPPED"
    assert obs.stop_sequence == 3


def test_scheduled_stop_with_only_a_sequence_now_maps() -> None:
    """A SCHEDULED stop that carries only its stop_sequence (no time/delay) is real
    operational content now (which stop, in which trip) -- it maps to a
    StopTimeObservation rather than being quarantined as it was under Outcome."""
    adapter, _ = example_gtfs_realtime_adapter()
    result = adapter.parse(
        example_trip_update_stop_row(arrival_delay=None, stop_schedule_relationship="SCHEDULED")
    )

    assert not result.is_quarantined
    obs = result.record
    assert isinstance(obs, StopTimeObservation)
    assert obs.stop_sequence == 3
    assert obs.schedule_relationship == "SCHEDULED"
    assert obs.arrival_delay_seconds is None


def test_extra_vendor_field_is_recorded_as_unmapped_extension() -> None:
    """A field outside the schema this adapter was written against (e.g. an NYCT
    proto extension surfaced as a dict key) must surface as 'unmapped_extension',
    not vanish."""
    adapter, _ = example_gtfs_realtime_adapter()
    result = adapter.parse(example_vehicle_position_row(nyct_train_id="06 0123+"))

    assert not result.is_quarantined
    extensions = [
        loss
        for loss in result.semantic_loss
        if loss.disposition == "unmapped_extension" and loss.source_field == "nyct_train_id"
    ]
    assert len(extensions) == 1
    assert extensions[0].source_value == "06 0123+"


def test_adapter_maps_the_real_acquired_gtfs_realtime_samples_from_disk() -> None:
    """Reads the REAL acquired GTFS-Realtime samples (data/standards/gtfs-rt-*.pb
    and *.asciipb: an MBTA VehiclePositions binary snapshot and the Apache-2.0
    google/transit TripUpdate example), maps their actual entities to observations,
    and schema-validates every mapped record. Skips cleanly if the protobuf
    bindings or the samples are absent."""
    import pytest

    if not BINDINGS_AVAILABLE:
        pytest.skip("gtfs-realtime-bindings not installed")

    pb_samples = sorted(glob.glob(str(STANDARDS_DIR / "gtfs-rt-*.pb")))
    samples = pb_samples + sorted(glob.glob(str(STANDARDS_DIR / "gtfs-rt-*.asciipb")))
    if not samples:
        pytest.skip(f"no gtfs-rt-*.pb / *.asciipb samples found under {STANDARDS_DIR}")

    adapter, _ = example_gtfs_realtime_adapter()
    mapped_vehicles = 0
    mapped_stop_times = 0
    quarantined = 0
    saw_in_transit = False
    saw_position = False
    for sample in samples:
        rows = list(read_gtfs_realtime_feed(sample))
        assert rows, f"acquired sample {sample} yielded no rows"
        for result in (adapter.parse(row) for row in rows):
            if result.is_quarantined:
                quarantined += 1
                assert result.quarantine.reason
                continue
            record = result.record
            model = type(record)
            errors = verify_against_schema(record.model_dump(mode="json"), model)
            assert errors == []
            if isinstance(record, VehicleObservation):
                mapped_vehicles += 1
                if record.current_status == "IN_TRANSIT_TO":
                    saw_in_transit = True
                if record.latitude is not None and record.longitude is not None:
                    saw_position = True
            elif isinstance(record, StopTimeObservation):
                mapped_stop_times += 1
            # No synthetic-request loss must ever appear now:
            assert not any("rider request" in loss.reason for loss in result.semantic_loss)

    assert mapped_vehicles + mapped_stop_times > 0, "no entity from any real sample mapped"
    if pb_samples:
        # A VehiclePositions snapshot: every position maps (no STOPPED_AT gate), so
        # live in-transit telemetry -- previously quarantined -- is now recorded.
        assert mapped_vehicles > 0
        assert saw_in_transit, "expected at least one IN_TRANSIT_TO vehicle to map now"
        assert saw_position, "expected a mapped vehicle to carry a lat/lon position"
