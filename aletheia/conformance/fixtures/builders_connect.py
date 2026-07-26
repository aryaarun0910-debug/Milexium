"""Shared example builders for themis/connect (Program B, first slice).

New file, not an edit to aletheia/conformance/fixtures/builders.py, per this packet's
owned-path boundary -- avoids colliding with the Program A/G fixtures another
packet already owns.
"""

from __future__ import annotations

from datetime import datetime, timezone

from themis.canonical import TenantId, new_id
from themis.connect import ReferenceAgencyTripsAdapter


def utc(*args, **kwargs) -> datetime:
    return datetime(*args, tzinfo=timezone.utc, **kwargs)


def example_trip_row(**overrides: str) -> dict:
    """One row shaped exactly like forge/business/reference_agency/output/trips.csv."""

    row = {
        "date": "2025-07-01",
        "hour": "11",
        "rider_id": "R0022",
        "origin_zone": "Z11",
        "dest_zone": "Z28",
        "purpose": "dialysis",
        "wheelchair": "False",
        "subscription": "True",
        "req_minute": "54",
        "status": "completed",
    }
    row.update(overrides)
    return row


def example_trips_adapter() -> tuple[ReferenceAgencyTripsAdapter, TenantId]:
    tenant_id = new_id(TenantId)
    adapter = ReferenceAgencyTripsAdapter(tenant_id, recorded_at=utc(2026, 7, 23, 9, 0))
    return adapter, tenant_id
