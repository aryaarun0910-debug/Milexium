"""Fixture-level conformance for packages/connect/gtfs_realtime.py: a
well-formed GTFS-Realtime operational signal maps to a schema-valid canonical
``Outcome`` -- the closest operational record -- and every meaning GTFS-RT
carries that Outcome has no home for (above all, the absence of any rider
request) is recorded as semantic loss rather than silently discarded
(blueprint/03-connect-and-standards.md).

Status: Demonstrated only -- open public real-time transit data (the Apache-2.0
GTFS-Realtime spec example and an open MBTA feed snapshot), not consented
operator data.
"""

from __future__ import annotations

import glob
from datetime import datetime, timezone
from pathlib import Path

from packages.canonical import Outcome
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


def test_stopped_vehicle_maps_to_a_schema_valid_outcome() -> None:
    adapter, tenant_id = example_gtfs_realtime_adapter()
    result = adapter.parse(example_vehicle_position_row())

    assert not result.is_quarantined
    assert result.quarantine is None
    outcome = result.record
    assert isinstance(outcome, Outcome)
    assert outcome.tenant_id == tenant_id
    assert outcome.served is True
    # A STOPPED_AT vehicle is an observed arrival -> actual_pickup_at from its epoch.
    assert outcome.actual_pickup_at == _utc_from_epoch(1690004805)
    # A VehiclePosition carries no schedule reference, so on-time-ness is unknown.
    assert outcome.on_time is None

    errors = verify_against_schema(outcome.model_dump(mode="json"), Outcome)
    assert errors == []


def test_vehicle_falls_back_to_feed_timestamp_when_vehicle_timestamp_absent() -> None:
    adapter, _ = example_gtfs_realtime_adapter()
    row = example_vehicle_position_row()
    del row["vehicle_timestamp"]

    result = adapter.parse(row)

    assert not result.is_quarantined
    # feed_timestamp = 1690004800 is used instead.
    assert result.record.actual_pickup_at == _utc_from_epoch(1690004800)


def test_synthetic_request_id_is_recorded_as_the_core_model_gap() -> None:
    """The headline finding: GTFS-RT has no rider request, so Outcome.request_id
    is a synthetic placeholder referencing no ServiceRequest -- and that must be
    recorded, because it is the operational-vs-request model mismatch itself."""

    adapter, _ = example_gtfs_realtime_adapter()
    result = adapter.parse(example_vehicle_position_row())

    gap = [
        loss
        for loss in result.semantic_loss
        if loss.source_field == "<no rider request in GTFS-Realtime>"
    ]
    assert len(gap) == 1
    assert gap[0].disposition == "coerced"
    assert "no request-independent operational entity" in gap[0].reason


def test_vehicle_operational_context_is_recorded_as_loss() -> None:
    """Outcome has no stop/vehicle/route/position/occupancy fields, so almost
    everything the vehicle feed says is loss -- the second half of the gap."""

    adapter, _ = example_gtfs_realtime_adapter()
    result = adapter.parse(example_vehicle_position_row())

    lost = {loss.source_field: loss for loss in result.semantic_loss}
    assert lost["stop_id"].disposition == "dropped"
    assert lost["stop_id"].source_value == "1259"
    assert lost["position_latitude"].disposition == "dropped"
    assert lost["occupancy_status"].source_value == "MANY_SEATS_AVAILABLE"
    assert lost["route_id"].source_value == "44"
    # served=True is a coercion (vehicle serviced the stop, not a rider request).
    served = lost["<Outcome.served has no GTFS-RT source>"]
    assert served.disposition == "coerced"


def test_trip_update_delay_maps_onto_on_time() -> None:
    adapter, _ = example_gtfs_realtime_adapter()
    result = adapter.parse(example_trip_update_stop_row(arrival_delay=5))

    assert not result.is_quarantined
    outcome = result.record
    assert outcome.served is True
    # +5s is within the 60s tolerance -> on time.
    assert outcome.on_time is True
    # A TripUpdate is a prediction, not an observation: no actual pickup.
    assert outcome.actual_pickup_at is None
    errors = verify_against_schema(outcome.model_dump(mode="json"), Outcome)
    assert errors == []

    delay_loss = [loss for loss in result.semantic_loss if loss.source_field == "arrival_delay"]
    assert len(delay_loss) == 1
    assert delay_loss[0].disposition == "coerced"
    assert "predicted" in delay_loss[0].reason


def test_trip_update_large_delay_is_not_on_time() -> None:
    adapter, _ = example_gtfs_realtime_adapter()
    result = adapter.parse(example_trip_update_stop_row(arrival_delay=600))

    assert result.record.on_time is False


def test_skipped_stop_maps_cleanly_to_served_false() -> None:
    """SKIPPED is the one TripUpdate signal that maps without coercion: an
    observed decision the stop will not be served -> served=False."""

    adapter, _ = example_gtfs_realtime_adapter()
    result = adapter.parse(
        example_trip_update_stop_row(
            stop_schedule_relationship="SKIPPED", arrival_delay=None
        )
    )

    assert not result.is_quarantined
    assert result.record.served is False
    assert result.record.on_time is None

    skip_loss = [
        loss for loss in result.semantic_loss if loss.source_field == "stop_schedule_relationship"
    ]
    assert len(skip_loss) == 1
    assert skip_loss[0].source_value == "SKIPPED"


def test_predicted_arrival_time_has_no_observed_home_and_is_recorded() -> None:
    adapter, _ = example_gtfs_realtime_adapter()
    result = adapter.parse(
        example_trip_update_stop_row(arrival_time=1690004900, arrival_delay=30)
    )

    assert result.record.actual_pickup_at is None
    time_loss = [
        loss
        for loss in result.semantic_loss
        if loss.source_field == "arrival_time/departure_time"
    ]
    assert len(time_loss) == 1
    assert time_loss[0].disposition == "dropped"
    assert "predicted-time" in time_loss[0].reason


def test_extra_vendor_field_is_recorded_as_unmapped_extension() -> None:
    """A field outside the schema this adapter was written against (e.g. an
    NYCT proto extension surfaced as a dict key) must surface as
    'unmapped_extension', not vanish."""

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
    """Reads the REAL acquired GTFS-Realtime samples in this repo
    (data/standards/gtfs-rt-*.pb and *.asciipb: an MBTA VehiclePositions binary
    snapshot and the Apache-2.0 google/transit TripUpdate example), maps their
    actual entities to Outcomes, and schema-validates every mapped record. Skips
    cleanly if the protobuf bindings or the samples are absent."""

    import pytest

    if not BINDINGS_AVAILABLE:
        pytest.skip("gtfs-realtime-bindings not installed")

    pb_samples = sorted(glob.glob(str(STANDARDS_DIR / "gtfs-rt-*.pb")))
    samples = pb_samples + sorted(glob.glob(str(STANDARDS_DIR / "gtfs-rt-*.asciipb")))
    if not samples:
        pytest.skip(f"no gtfs-rt-*.pb / *.asciipb samples found under {STANDARDS_DIR}")

    adapter, _ = example_gtfs_realtime_adapter()
    total_mapped = 0
    saw_observed_arrival = False
    for sample in samples:
        rows = list(read_gtfs_realtime_feed(sample))
        assert rows, f"acquired sample {sample} yielded no rows"
        for result in (adapter.parse(row) for row in rows):
            if result.is_quarantined:
                assert result.quarantine.reason
                continue
            total_mapped += 1
            errors = verify_against_schema(result.record.model_dump(mode="json"), Outcome)
            assert errors == []
            if result.record.actual_pickup_at is not None:
                saw_observed_arrival = True

    assert total_mapped > 0, "no entity from any real acquired sample mapped successfully"
    # A VehiclePositions (.pb) snapshot should yield at least one observed arrival;
    # only assert this when such a sample is actually present (the .asciipb
    # TripUpdate example carries predictions, never an observed arrival).
    if pb_samples:
        assert saw_observed_arrival, "expected a STOPPED_AT arrival with an actual_pickup_at"
