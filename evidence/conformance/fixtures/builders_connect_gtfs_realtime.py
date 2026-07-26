"""Shared example builders for app/connect/gtfs_realtime.py.

New file, not an edit to the other builders_connect_*.py, per this packet's
owned-path boundary. The example rows are shaped exactly like
``feed_message_to_rows`` yields, so a test can exercise the dict-only adapter
without the protobuf bindings. Values are drawn from real GTFS-Realtime data:
the VehiclePosition example mirrors an MBTA route-44 bus (STOPPED_AT), and the
TripUpdate example mirrors the Apache-2.0 google/transit trip-updates-full
example (a +5s predicted arrival delay).
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.canonical import TenantId, new_id
from app.connect.gtfs_realtime import GtfsRealtimeAdapter


def utc(*args, **kwargs) -> datetime:
    return datetime(*args, tzinfo=timezone.utc, **kwargs)


# 2023-07-22T05:46:40Z, an arbitrary fixed epoch for reproducible timestamps.
_FEED_EPOCH = 1690004800
_VEHICLE_EPOCH = 1690004805


def example_vehicle_position_row(**overrides: object) -> dict:
    """A STOPPED_AT VehiclePosition row (the one cleanly-mappable vehicle
    signal), shaped like feed_message_to_rows yields. Mirrors an MBTA route-44
    bus observed stopped at stop 1259."""

    row: dict = {
        "_gtfs_rt_kind": "vehicle_position",
        "entity_id": "y1860",
        "feed_gtfs_realtime_version": "2.0",
        "feed_incrementality": "FULL_DATASET",
        "feed_timestamp": _FEED_EPOCH,
        "trip_id": "76573594",
        "route_id": "44",
        "direction_id": 0,
        "trip_start_date": "20230722",
        "trip_schedule_relationship": "SCHEDULED",
        "vehicle_id": "y1860",
        "vehicle_label": "1860",
        "position_latitude": 42.3311,
        "position_longitude": -71.0905,
        "position_bearing": 97.0,
        "current_stop_sequence": 3,
        "stop_id": "1259",
        "current_status": "STOPPED_AT",
        "vehicle_timestamp": _VEHICLE_EPOCH,
        "occupancy_status": "MANY_SEATS_AVAILABLE",
    }
    row.update(overrides)
    return row


def example_trip_update_stop_row(**overrides: object) -> dict:
    """One exploded TripUpdate stop_time_update row, shaped like
    feed_message_to_rows yields. Mirrors the google/transit example: a +5s
    predicted arrival delay on stop_sequence 3 of trip-1."""

    row: dict = {
        "_gtfs_rt_kind": "trip_update_stop",
        "entity_id": "simple-trip",
        "feed_gtfs_realtime_version": "2.0",
        "feed_incrementality": "FULL_DATASET",
        "feed_timestamp": _FEED_EPOCH,
        "trip_id": "trip-1",
        "trip_update_timestamp": _FEED_EPOCH,
        "_stop_time_update_present": True,
        "_stop_time_update_index": 0,
        "_stop_time_update_count": 1,
        "stop_sequence": 3,
        "arrival_delay": 5,
        "stop_schedule_relationship": "SCHEDULED",
    }
    row.update(overrides)
    return row


def example_alert_row(**overrides: object) -> dict:
    row: dict = {
        "_gtfs_rt_kind": "alert",
        "entity_id": "alert-1",
        "feed_gtfs_realtime_version": "2.0",
        "feed_incrementality": "FULL_DATASET",
        "feed_timestamp": _FEED_EPOCH,
        "alert_cause": "CONSTRUCTION",
        "alert_effect": "DETOUR",
        "alert_header_text": "Route 44 detour",
        "alert_informed_entity_count": 1,
    }
    row.update(overrides)
    return row


def example_gtfs_realtime_adapter() -> tuple[GtfsRealtimeAdapter, TenantId]:
    tenant_id = new_id(TenantId)
    adapter = GtfsRealtimeAdapter(tenant_id, recorded_at=utc(2026, 7, 24, 9, 0))
    return adapter, tenant_id
