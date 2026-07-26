"""Shared example builders for themis/connect/tlc_trips.py.

New file, not an edit to aletheia/conformance/fixtures/builders_connect.py, per this
packet's owned-path boundary -- avoids colliding with the reference_agency
adapter's fixtures another packet already owns.
"""

from __future__ import annotations

from datetime import datetime, timezone

from themis.canonical import TenantId, new_id
from themis.connect.tlc_trips import TlcTripsAdapter


def utc(*args, **kwargs) -> datetime:
    return datetime(*args, tzinfo=timezone.utc, **kwargs)


def example_tlc_row(**overrides: object) -> dict:
    """One row shaped exactly like a real data/curated/raw_tlc/fhvhv_tripdata_*.parquet
    row (values and column names taken from an actual row read from
    fhvhv_tripdata_2019-02.parquet during adapter development)."""

    row: dict = {
        "hvfhs_license_num": "HV0003",
        "dispatching_base_num": "B02867",
        "originating_base_num": "B02867",
        "request_datetime": datetime(2019, 2, 1, 0, 1, 26),
        "on_scene_datetime": datetime(2019, 2, 1, 0, 2, 55),
        "pickup_datetime": datetime(2019, 2, 1, 0, 5, 18),
        "dropoff_datetime": datetime(2019, 2, 1, 0, 14, 57),
        "PULocationID": 245,
        "DOLocationID": 251,
        "trip_miles": 2.45,
        "trip_time": 579,
        "base_passenger_fare": 9.35,
        "tolls": 0.0,
        "bcf": 0.23,
        "sales_tax": 0.83,
        "congestion_surcharge": 0.0,
        "airport_fee": None,
        "tips": 0.0,
        "driver_pay": 7.48,
        "shared_request_flag": "Y",
        "shared_match_flag": "N",
        "access_a_ride_flag": "N",
        "wav_request_flag": "N",
        "wav_match_flag": None,
    }
    row.update(overrides)
    return row


def example_tlc_adapter() -> tuple[TlcTripsAdapter, TenantId]:
    tenant_id = new_id(TenantId)
    adapter = TlcTripsAdapter(tenant_id, recorded_at=utc(2026, 7, 23, 9, 0))
    return adapter, tenant_id
