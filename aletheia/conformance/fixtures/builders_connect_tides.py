"""Shared example builders for themis/connect/tides_trips.py.

New file, not an edit to aletheia/conformance/fixtures/builders_connect.py or
builders_connect_tlc.py, per this packet's owned-path boundary -- avoids
colliding with the reference_agency and TLC adapter fixtures other packets
already own.

The row shape here matches the real TIDES trips_performed header acquired at
data/acquired/standards/tides-sample.*.csv exactly (that file is header-only, so the
data values below are hand-built fixtures against the real column names, the
same convention example_trip_row() uses for reference_agency).
"""

from __future__ import annotations

from datetime import datetime, timezone

from themis.canonical import TenantId, new_id
from themis.connect.tides_trips import TidesTripsAdapter

# The real TIDES trips_performed columns, in order, as they appear in the
# acquired header at data/acquired/standards/tides-sample.*.csv. The disk-header
# conformance test cross-checks the adapter's expected columns against this.
TIDES_TRIPS_PERFORMED_COLUMNS = (
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
    "trip_start_stop_id",
    "trip_end_stop_id",
    "schedule_trip_start",
    "schedule_trip_end",
    "actual_trip_start",
    "actual_trip_end",
    "trip_type",
    "schedule_relationship",
    "service_date",
)


def utc(*args, **kwargs) -> datetime:
    return datetime(*args, tzinfo=timezone.utc, **kwargs)


def example_tides_row(**overrides: object) -> dict:
    """One row shaped exactly like a TIDES trips_performed CSV row (string
    cells, real column names). Values are a realistic demand-responsive trip."""

    row: dict = {
        "date": "2025-07-01",
        "trip_id_performed": "TP-100045",
        "vehicle_id": "VH-07",
        "trip_id_scheduled": "TS-90012",
        "route_id": "DR-FLEX-1",
        "route_type": "715",
        "shape_id": "SHP-DR-1",
        "direction_id": "0",
        "operator_id": "OP-CENTRAL",
        "block_id": "BLK-3",
        "trip_start_stop_id": "STOP-114",
        "trip_end_stop_id": "STOP-256",
        "schedule_trip_start": "2025-07-01T08:15:00",
        "schedule_trip_end": "2025-07-01T08:47:00",
        "actual_trip_start": "2025-07-01T08:19:00",
        "actual_trip_end": "2025-07-01T08:51:00",
        "trip_type": "demand_response",
        "schedule_relationship": "scheduled",
        "service_date": "2025-07-01",
    }
    row.update(overrides)
    return row


def example_tides_adapter() -> tuple[TidesTripsAdapter, TenantId]:
    tenant_id = new_id(TenantId)
    adapter = TidesTripsAdapter(tenant_id, recorded_at=utc(2026, 7, 23, 9, 0))
    return adapter, tenant_id
