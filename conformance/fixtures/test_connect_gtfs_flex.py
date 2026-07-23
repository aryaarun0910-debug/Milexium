"""Fixture-level conformance for packages/connect/gtfs_flex.py: a GTFS-Flex
`stop_times` row (a *bookable service window*, not a performed trip) maps to a
schema-valid ServiceRequest; the flex booking window maps onto the paratransit
negotiated window; and every source meaning ServiceRequest v0.1 has no home
for -- including the fact that this is service availability, not an actual
request -- is reported as semantic loss rather than silently discarded
(blueprint/03-connect-and-standards.md, "no adapter leaks vendor-specific
meanings into Core... without recording").

Status: Demonstrated only -- an open-standard spec example feed (MobilityData
GTFS-Flex "on demand service", Apache-2.0), not consented operator data.
"""

from __future__ import annotations

import glob
from pathlib import Path

from packages.canonical import ServiceRequest, ServiceRequestState
from packages.connect.gtfs_flex import read_gtfs_flex_zip
from packages.verify import verify_against_schema

from conformance.fixtures.builders_connect_gtfs_flex import (
    example_gtfs_flex_adapter,
    example_gtfs_flex_row,
)

STANDARDS_DIR = Path(__file__).parents[2] / "data" / "standards"


def test_valid_flex_row_maps_to_a_schema_valid_service_request() -> None:
    adapter, tenant_id = example_gtfs_flex_adapter()
    result = adapter.parse(example_gtfs_flex_row())

    assert not result.is_quarantined
    assert result.quarantine is None
    request = result.record
    assert isinstance(request, ServiceRequest)
    assert request.tenant_id == tenant_id
    assert request.status == ServiceRequestState.REQUESTED
    assert request.meta.version == 1
    assert not request.meta.is_correction()
    # A single flex servable location becomes both zones (recorded as loss below).
    assert request.pickup_zone == "area_294"
    assert request.dropoff_zone == "area_294"
    assert request.mobility_device is None
    assert request.rider_ref.startswith("gtfs-flex-no-rider-")

    errors = verify_against_schema(request.model_dump(mode="json"), ServiceRequest)
    assert errors == []


def test_flex_booking_window_maps_onto_the_negotiated_window() -> None:
    """The standout mapping: GTFS-Flex's pickup/drop-off window IS the
    paratransit negotiated pickup window -- the first ServiceRequest field for
    it that any adapter in this repo has been able to populate from real data.
    Anchored to the service's first valid date (calendar.start_date=20220414)."""

    adapter, _ = example_gtfs_flex_adapter()
    result = adapter.parse(example_gtfs_flex_row())
    times = result.record.times

    assert times.negotiated_window_start.isoformat() == "2022-04-14T11:00:00+00:00"
    assert times.negotiated_window_end.isoformat() == "2022-04-14T23:00:00+00:00"
    # requested_at is coerced to the window-open instant (no per-request time exists).
    assert times.requested_at == times.negotiated_window_start
    assert times.scheduled_pickup_at is None
    assert times.actual_pickup_at is None

    window_loss = [
        loss
        for loss in result.semantic_loss
        if loss.source_field == "start_pickup_drop_off_window/end_pickup_drop_off_window"
    ]
    assert len(window_loss) == 1
    assert window_loss[0].disposition == "coerced"
    assert "negotiated" in window_loss[0].reason


def test_gtfs_time_past_midnight_rolls_into_the_next_day() -> None:
    """GTFS times may exceed 24:00:00 (service past midnight). A 25:30 window
    end must roll to 01:30 the following day, not be rejected."""

    adapter, _ = example_gtfs_flex_adapter()
    result = adapter.parse(example_gtfs_flex_row(end_pickup_drop_off_window="25:30:00"))

    assert not result.is_quarantined
    assert result.record.times.negotiated_window_end.isoformat() == "2022-04-15T01:30:00+00:00"


def test_service_availability_is_recorded_as_not_an_actual_request() -> None:
    """The genuine semantic distinction: status=REQUESTED is honest, but this
    is a bookable service template, not a request any rider has made -- and that
    must be recorded, not implied by the status alone."""

    adapter, _ = example_gtfs_flex_adapter()
    result = adapter.parse(example_gtfs_flex_row())

    template_loss = [
        loss
        for loss in result.semantic_loss
        if loss.source_field == "<service-availability template, not an actual rider request>"
    ]
    assert len(template_loss) == 1
    assert template_loss[0].disposition == "coerced"
    assert "observed demand" in template_loss[0].reason


def test_requested_at_coercion_is_recorded() -> None:
    adapter, _ = example_gtfs_flex_adapter()
    result = adapter.parse(example_gtfs_flex_row())

    requested_loss = [
        loss
        for loss in result.semantic_loss
        if loss.source_field == "<no per-request time in a GTFS-Flex feed>"
    ]
    assert len(requested_loss) == 1
    assert requested_loss[0].disposition == "coerced"


def test_single_location_becoming_both_zones_is_recorded_as_coercion() -> None:
    adapter, _ = example_gtfs_flex_adapter()
    result = adapter.parse(example_gtfs_flex_row())

    stop_loss = [loss for loss in result.semantic_loss if loss.source_field == "stop_id"]
    assert len(stop_loss) == 1
    assert stop_loss[0].disposition == "coerced"
    assert stop_loss[0].source_value == "area_294"


def test_rider_ref_is_synthetic_and_recorded_as_such() -> None:
    """GTFS-Flex has no rider identifier at all; two different rows must not
    collide onto the same rider_ref, and the omission must be recorded."""

    adapter, _ = example_gtfs_flex_adapter()
    result_a = adapter.parse(example_gtfs_flex_row(stop_sequence="1"))
    result_b = adapter.parse(example_gtfs_flex_row(stop_sequence="2"))

    assert result_a.record.rider_ref != result_b.record.rider_ref
    lost = [
        loss
        for loss in result_a.semantic_loss
        if loss.source_field == "<no rider/passenger identifier in a GTFS-Flex feed>"
    ]
    assert len(lost) == 1
    assert lost[0].disposition == "dropped"


def test_booking_rule_info_is_recorded_as_semantic_loss() -> None:
    """booking_type / prior_notice_duration / phone_number are rich, meaningful
    booking-rule facts ServiceRequest v0.1 has no field for -- they must be
    reported, not silently dropped on the floor."""

    from conformance.fixtures.builders_connect_gtfs_flex import example_booking_rule

    adapter, _ = example_gtfs_flex_adapter()
    result = adapter.parse(
        example_gtfs_flex_row(
            booking_rule=example_booking_rule(prior_notice_duration_min="120")
        )
    )

    lost_fields = {loss.source_field: loss for loss in result.semantic_loss}
    assert lost_fields["booking_rule.booking_type"].disposition == "dropped"
    assert lost_fields["booking_rule.booking_type"].source_value == "0"
    assert lost_fields["booking_rule.phone_number"].disposition == "dropped"
    assert lost_fields["booking_rule.phone_number"].source_value == "877-230-6045"
    assert lost_fields["booking_rule.prior_notice_duration_min"].source_value == "120"
    assert "advance-notice" in lost_fields["booking_rule.prior_notice_duration_min"].reason
    # Empty booking-rule fields carry no signal and are not reported.
    assert "booking_rule.prior_notice_duration_max" not in lost_fields


def test_meaningful_stop_times_fields_are_recorded_as_semantic_loss() -> None:
    adapter, _ = example_gtfs_flex_adapter()
    result = adapter.parse(example_gtfs_flex_row())

    lost_fields = {loss.source_field: loss for loss in result.semantic_loss}
    assert lost_fields["pickup_type"].disposition == "dropped"
    assert lost_fields["pickup_type"].source_value == "2"
    assert lost_fields["mean_duration_factor"].disposition == "dropped"
    # Empty stop_times cells (arrival_time/departure_time on a flex row) carry no signal.
    assert "arrival_time" not in lost_fields


def test_extra_vendor_stop_times_column_is_recorded_as_unmapped_extension() -> None:
    """A column outside the GTFS-Flex stop_times schema this adapter was written
    against must surface with disposition 'unmapped_extension', not vanish."""

    adapter, _ = example_gtfs_flex_adapter()
    result = adapter.parse(example_gtfs_flex_row(vendor_specific_col="XYZ"))

    assert not result.is_quarantined
    extension_losses = [
        loss
        for loss in result.semantic_loss
        if loss.disposition == "unmapped_extension" and loss.source_field == "vendor_specific_col"
    ]
    assert len(extension_losses) == 1
    assert extension_losses[0].source_value == "XYZ"


def test_adapter_maps_the_real_acquired_gtfs_flex_feed_from_disk() -> None:
    """Reads the REAL acquired GTFS-Flex feed already in this repo
    (data/standards/gtfs-flex-on-demand.*.zip), joins and maps its actual
    stop_times rows, and asserts the real booking window becomes the negotiated
    window. Skips cleanly if the feed is absent in this environment."""

    import pytest

    zips = sorted(glob.glob(str(STANDARDS_DIR / "gtfs-flex-on-demand.*.zip")))
    if not zips:
        pytest.skip(f"no gtfs-flex-on-demand.*.zip found under {STANDARDS_DIR}")

    rows = list(read_gtfs_flex_zip(zips[0]))
    assert rows, "acquired feed yielded no stop_times rows"

    adapter, _ = example_gtfs_flex_adapter()
    results = [adapter.parse(row) for row in rows]

    mapped = [r for r in results if not r.is_quarantined]
    assert mapped, "no real feed row mapped successfully"
    for result in results:
        if result.is_quarantined:
            assert result.quarantine.reason
            continue
        errors = verify_against_schema(result.record.model_dump(mode="json"), ServiceRequest)
        assert errors == []

    # The acquired feed's real Downtowner window is 11:00-23:00 on 2022-04-14.
    first = mapped[0].record
    assert first.times.negotiated_window_start.isoformat() == "2022-04-14T11:00:00+00:00"
    assert first.times.negotiated_window_end.isoformat() == "2022-04-14T23:00:00+00:00"
    assert first.pickup_zone == "area_294"
