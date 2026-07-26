"""Fixture-level conformance for app/connect/tlc_trips.py: a real NYC
TLC FHVHV trip row maps to a schema-valid ServiceRequest, and every source
field ServiceRequest v0.1 has no home for is reported as semantic loss
rather than silently discarded (blueprint/03-connect-and-standards.md, "no
adapter leaks vendor-specific meanings into Core... without recording").
Status: Demonstrated only -- FHVHV is real public data, not consented
paratransit operator data (see app/connect/tlc_trips.py docstring).
"""

from __future__ import annotations

from pathlib import Path

from app.canonical import ServiceRequest, ServiceRequestState
from app.verify import verify_against_schema

from conformance.fixtures.builders_connect_tlc import example_tlc_adapter, example_tlc_row

RAW_TLC_DIR = Path(__file__).parents[3] / "realdata" / "raw_tlc"


def test_valid_trip_row_maps_to_a_schema_valid_service_request() -> None:
    adapter, tenant_id = example_tlc_adapter()
    result = adapter.parse(example_tlc_row())

    assert not result.is_quarantined
    assert result.quarantine is None
    request = result.record
    assert isinstance(request, ServiceRequest)
    assert request.tenant_id == tenant_id
    assert request.status == ServiceRequestState.REQUESTED
    assert request.meta.version == 1
    assert not request.meta.is_correction()
    assert request.pickup_zone == "245"
    assert request.dropoff_zone == "251"
    assert request.mobility_device is None  # wav_request_flag="N" in the fixture row
    assert request.times.requested_at.isoformat() == "2019-02-01T00:01:26+00:00"
    assert request.times.actual_pickup_at.isoformat() == "2019-02-01T00:05:18+00:00"
    assert request.times.negotiated_window_start is None
    assert request.times.scheduled_pickup_at is None
    assert request.rider_ref.startswith("tlc-no-rider-")

    errors = verify_against_schema(request.model_dump(mode="json"), ServiceRequest)
    assert errors == []


def test_wav_request_flag_y_maps_to_mobility_device() -> None:
    adapter, _ = example_tlc_adapter()
    result = adapter.parse(example_tlc_row(wav_request_flag="Y"))
    assert result.record.mobility_device == "wheelchair"


def test_missing_wav_request_flag_is_dropped_not_silently_unset() -> None:
    """An absent field with no signal must still surface as a recorded
    semantic-loss entry, not just an unremarked None on the record."""

    adapter, _ = example_tlc_adapter()
    result = adapter.parse(example_tlc_row(wav_request_flag=None))

    assert result.record.mobility_device is None
    lost = [loss for loss in result.semantic_loss if loss.source_field == "wav_request_flag"]
    assert len(lost) == 1
    assert lost[0].disposition == "dropped"
    assert lost[0].source_value is None


def test_rider_ref_is_never_a_stable_identity_and_is_documented_as_such() -> None:
    """FHVHV has no rider identifier at all; two different trips must not
    collide onto the same rider_ref, and the omission must be recorded."""

    adapter, _ = example_tlc_adapter()
    result_a = adapter.parse(example_tlc_row())
    result_b = adapter.parse(example_tlc_row(PULocationID=99, DOLocationID=100))

    assert result_a.record.rider_ref != result_b.record.rider_ref
    lost = [
        loss for loss in result_a.semantic_loss if loss.source_field == "<no rider/passenger identifier column>"
    ]
    assert len(lost) == 1
    assert lost[0].disposition == "dropped"


def test_known_but_uncovered_source_fields_are_recorded_as_semantic_loss() -> None:
    """trip_miles/driver_pay/access_a_ride_flag/wav_match_flag are real,
    meaningful FHVHV columns ServiceRequest v0.1 has no field for -- they
    must be reported, not silently dropped on the floor."""

    adapter, _ = example_tlc_adapter()
    result = adapter.parse(example_tlc_row())

    lost_fields = {loss.source_field: loss for loss in result.semantic_loss}
    assert lost_fields["trip_miles"].disposition == "dropped"
    assert lost_fields["trip_miles"].source_value == "2.45"
    assert lost_fields["driver_pay"].disposition == "dropped"
    assert lost_fields["access_a_ride_flag"].disposition == "dropped"
    assert lost_fields["hvfhs_license_num"].source_value == "HV0003"
    assert "request_datetime" in lost_fields
    assert lost_fields["request_datetime"].disposition == "coerced"
    assert lost_fields["pickup_datetime"].disposition == "coerced"


def test_extra_vendor_field_is_recorded_as_an_unmapped_extension() -> None:
    """A field outside the 24-column schema this adapter was written
    against (e.g. cbd_congestion_fee, a real column TLC added in 2025) must
    surface with disposition 'unmapped_extension', not vanish or raise."""

    adapter, _ = example_tlc_adapter()
    result = adapter.parse(example_tlc_row(cbd_congestion_fee=1.5))

    assert not result.is_quarantined
    extension_losses = [loss for loss in result.semantic_loss if loss.disposition == "unmapped_extension"]
    assert len(extension_losses) == 1
    assert extension_losses[0].source_field == "cbd_congestion_fee"
    assert extension_losses[0].source_value == "1.5"


def test_adapter_maps_a_real_sample_from_disk_without_loading_the_whole_file() -> None:
    """Runs against a small real sample pulled directly from an actual
    fhvhv_tripdata_*.parquet file already on disk in this repo -- not a
    hand-written stand-in for the source shape. Skips cleanly if the raw
    TLC corpus is not present in this environment (it is gitignored)."""

    import glob

    import pytest

    files = sorted(glob.glob(str(RAW_TLC_DIR / "fhvhv_tripdata_*.parquet")))
    if not files:
        pytest.skip(f"no fhvhv_tripdata_*.parquet files found under {RAW_TLC_DIR}")

    duckdb = pytest.importorskip("duckdb")
    con = duckdb.connect()
    con.execute("PRAGMA disable_progress_bar")
    df = con.execute(f"SELECT * FROM read_parquet('{files[0]}') LIMIT 500").fetchdf()
    rows = df.to_dict(orient="records")

    adapter, _ = example_tlc_adapter()
    results = [adapter.parse(row) for row in rows]

    assert len(results) == 500
    for result in results:
        if result.is_quarantined:
            assert result.quarantine.reason
            continue
        errors = verify_against_schema(result.record.model_dump(mode="json"), ServiceRequest)
        assert errors == []
