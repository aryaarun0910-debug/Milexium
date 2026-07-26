"""Adversarial fixtures for app/connect/gtfs_flex.py: malformed or
out-of-scope GTFS-Flex rows must be quarantined with a clear reason -- never
silently dropped, never an uncaught exception that kills the batch
(blueprint/03-connect-and-standards.md mapping rule 7: "quarantine impossible
or policy-sensitive records rather than guessing"). The two headline cases the
packet calls out -- an unparseable booking-window time, and a stop_times row
that references a booking_rule_id not present in booking_rules.txt (a real
feed-integrity failure mode) -- are both covered here.
"""

from __future__ import annotations

from app.connect.adapter import QuarantinedRow, parse_batch

from conformance.fixtures.builders_connect_gtfs_flex import (
    example_gtfs_flex_adapter,
    example_gtfs_flex_row,
)


def test_row_missing_required_window_time_is_quarantined_not_dropped() -> None:
    adapter, _ = example_gtfs_flex_adapter()
    row = example_gtfs_flex_row(end_pickup_drop_off_window="")

    result = adapter.parse(row)

    assert result.is_quarantined
    assert result.record is None
    assert result.semantic_loss == ()
    assert isinstance(result.quarantine, QuarantinedRow)
    assert "end_pickup_drop_off_window" in result.quarantine.reason
    assert result.quarantine.failed_field == "end_pickup_drop_off_window"
    assert result.quarantine.raw_row["stop_id"] == "area_294"  # original row preserved for re-run


def test_row_with_unparseable_window_time_is_quarantined_with_a_clear_reason() -> None:
    adapter, _ = example_gtfs_flex_adapter()
    row = example_gtfs_flex_row(start_pickup_drop_off_window="not-a-time")

    result = adapter.parse(row)

    assert result.is_quarantined
    assert "not-a-time" in result.quarantine.reason
    assert "start_pickup_drop_off_window" in result.quarantine.reason


def test_dangling_booking_rule_reference_is_quarantined() -> None:
    """Real feed-integrity failure mode: a stop_times row references a
    booking_rule_id that is not present in booking_rules.txt."""

    adapter, _ = example_gtfs_flex_adapter()
    row = example_gtfs_flex_row(
        pickup_booking_rule_id="booking_does_not_exist",
        drop_off_booking_rule_id="booking_does_not_exist",
        booking_rule=None,
    )

    result = adapter.parse(row)

    assert result.is_quarantined
    assert "booking_does_not_exist" in result.quarantine.reason
    assert "booking_rules.txt" in result.quarantine.reason
    assert result.quarantine.failed_field == "pickup_booking_rule_id"


def test_row_with_no_booking_rule_reference_is_quarantined_as_out_of_scope() -> None:
    adapter, _ = example_gtfs_flex_adapter()
    row = example_gtfs_flex_row(
        pickup_booking_rule_id="",
        drop_off_booking_rule_id="",
        booking_rule=None,
    )

    result = adapter.parse(row)

    assert result.is_quarantined
    assert "no booking_rule_id" in result.quarantine.reason


def test_row_with_no_anchor_date_is_quarantined() -> None:
    """Without a calendar service date or a feed date, the daily-recurring flex
    window cannot be anchored on a concrete calendar day."""

    adapter, _ = example_gtfs_flex_adapter()
    row = example_gtfs_flex_row(service_start_date="", feed_start_date="")

    result = adapter.parse(row)

    assert result.is_quarantined
    assert "anchor" in result.quarantine.reason
    assert result.quarantine.failed_field == "service_start_date"


def test_window_end_before_start_is_quarantined() -> None:
    adapter, _ = example_gtfs_flex_adapter()
    row = example_gtfs_flex_row(
        start_pickup_drop_off_window="23:00:00",
        end_pickup_drop_off_window="11:00:00",
    )

    result = adapter.parse(row)

    assert result.is_quarantined
    assert "before" in result.quarantine.reason
    assert result.quarantine.failed_field == "end_pickup_drop_off_window"


def test_feed_start_date_is_used_when_no_calendar_service_date_exists() -> None:
    """Not a quarantine: when calendar.start_date is absent, the adapter falls
    back to feed_info.feed_start_date to anchor the window rather than failing."""

    adapter, _ = example_gtfs_flex_adapter()
    row = example_gtfs_flex_row(service_start_date="")

    result = adapter.parse(row)

    assert not result.is_quarantined
    # feed_start_date=20221031 in the fixture.
    assert result.record.times.negotiated_window_start.isoformat() == "2022-10-31T11:00:00+00:00"


def test_batch_with_one_bad_row_quarantines_only_that_row() -> None:
    adapter, _ = example_gtfs_flex_adapter()
    rows = [
        example_gtfs_flex_row(stop_sequence="1"),
        example_gtfs_flex_row(stop_sequence="2", start_pickup_drop_off_window="not-a-time"),
        example_gtfs_flex_row(stop_sequence="3"),
    ]

    results = parse_batch(adapter, rows)

    assert len(results) == 3
    assert not results[0].is_quarantined
    assert results[1].is_quarantined
    assert not results[2].is_quarantined
    assert results[0].record.rider_ref != results[2].record.rider_ref
