"""Shared example builders for themis/connect/gtfs_flex.py.

New file, not an edit to the other builders_connect_*.py, per this packet's
owned-path boundary -- avoids colliding with adapter fixtures other packets own.

example_gtfs_flex_row() returns a dict shaped exactly like what
read_gtfs_flex_zip() yields for the acquired feed's first stop_times row: the
raw GTFS-Flex stop_times columns plus the pre-joined `booking_rule`,
service-date, and feed-date context. Values are taken verbatim from
data/acquired/standards/gtfs-flex-on-demand.*.zip (City of Aspen "Downtowner" flex
service, published by Trillium; Apache-2.0 spec example).
"""

from __future__ import annotations

from datetime import datetime, timezone

from themis.canonical import TenantId, new_id
from themis.connect.gtfs_flex import GtfsFlexAdapter


def utc(*args, **kwargs) -> datetime:
    return datetime(*args, tzinfo=timezone.utc, **kwargs)


def example_booking_rule(**overrides: object) -> dict:
    """The acquired feed's single booking rule (booking_route_17102)."""

    rule: dict = {
        "booking_rule_id": "booking_route_17102",
        "booking_type": "0",
        "prior_notice_duration_min": "",
        "prior_notice_duration_max": "",
        "prior_notice_start_day": "",
        "prior_notice_start_time": "",
        "prior_notice_last_day": "",
        "prior_notice_last_time": "",
        "prior_notice_service_id": "",
        "message": (
            "The Downtowner provides free door-to-door transportation within the downtown area "
            "of Aspen. To schedule a ride, use the Downtowner Android/iOS mobile app. You may "
            "also request a ride by calling (877) 230-6045."
        ),
        "pickup_message": "",
        "drop_off_message": "",
        "phone_number": "877-230-6045",
        "info_url": "https://www.cityofaspen.com/270/Downtowner",
        "booking_url": "",
    }
    rule.update(overrides)
    return rule


def example_gtfs_flex_row(**overrides: object) -> dict:
    """One adapter-input dict shaped exactly like read_gtfs_flex_zip() yields
    for the acquired feed's first (pickup) stop_times row."""

    row: dict = {
        "trip_id": "t_1854078_b_29084_tn_0",
        "arrival_time": "",
        "departure_time": "",
        "stop_id": "area_294",
        "stop_sequence": "1",
        "stop_headsign": "",
        "pickup_type": "2",
        "drop_off_type": "1",
        "shape_dist_traveled": "0",
        "timepoint": "0",
        "continuous_pickup": "1",
        "continuous_drop_off": "1",
        "pickup_booking_rule_id": "booking_route_17102",
        "drop_off_booking_rule_id": "booking_route_17102",
        "start_pickup_drop_off_window": "11:00:00",
        "end_pickup_drop_off_window": "23:00:00",
        "mean_duration_factor": "1",
        "mean_duration_offset": "9.00",
        "safe_duration_factor": "1",
        "safe_duration_offset": "20.00",
        "tts_stop_headsign": "",
        # Pre-joined context attached by read_gtfs_flex_zip():
        "booking_rule": example_booking_rule(),
        "service_id": "c_20808_b_29084_d_127",
        "service_start_date": "20220414",
        "service_end_date": "20221123",
        "feed_start_date": "20221031",
    }
    row.update(overrides)
    return row


def example_gtfs_flex_adapter() -> tuple[GtfsFlexAdapter, TenantId]:
    tenant_id = new_id(TenantId)
    adapter = GtfsFlexAdapter(tenant_id, recorded_at=utc(2026, 7, 23, 9, 0))
    return adapter, tenant_id
