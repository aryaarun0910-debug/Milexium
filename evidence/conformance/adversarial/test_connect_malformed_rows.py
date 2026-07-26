"""Adversarial fixtures for app/connect's first adapter slice
(Program B): malformed rows must be quarantined with a clear reason --
never silently dropped, never an uncaught exception that kills the batch
(blueprint/03-connect-and-standards.md mapping rule 7: "quarantine
impossible or policy-sensitive records rather than guessing").
"""

from __future__ import annotations

from app.connect import AdapterResult, QuarantinedRow, parse_batch

from conformance.fixtures.builders_connect import example_trip_row, example_trips_adapter


def test_row_missing_required_pickup_date_is_quarantined_not_dropped() -> None:
    adapter, _ = example_trips_adapter()
    row = example_trip_row(date="")

    result = adapter.parse(row)

    assert result.is_quarantined
    assert result.record is None
    assert result.semantic_loss == ()
    assert isinstance(result.quarantine, QuarantinedRow)
    assert "date" in result.quarantine.reason
    assert result.quarantine.failed_field == "date"
    assert result.quarantine.raw_row["rider_id"] == "R0022"  # original row preserved for re-run


def test_row_with_invalid_mobility_device_value_is_quarantined_with_a_clear_reason() -> None:
    adapter, _ = example_trips_adapter()
    row = example_trip_row(wheelchair="unspecified_maybe")

    result = adapter.parse(row)

    assert result.is_quarantined
    assert "unspecified_maybe" in result.quarantine.reason
    assert "wheelchair" in result.quarantine.reason.lower()


def test_out_of_range_hour_is_quarantined_rather_than_wrapped_to_the_next_day() -> None:
    adapter, _ = example_trips_adapter()
    row = example_trip_row(hour="27")

    result = adapter.parse(row)

    assert result.is_quarantined
    assert "27" in result.quarantine.reason


def test_batch_with_one_bad_row_quarantines_only_that_row() -> None:
    adapter, _ = example_trips_adapter()
    rows = [
        example_trip_row(rider_id="R0001"),
        example_trip_row(rider_id="R0002", date=""),
        example_trip_row(rider_id="R0003"),
    ]

    results = parse_batch(adapter, rows)

    assert len(results) == 3
    assert not results[0].is_quarantined
    assert results[1].is_quarantined
    assert not results[2].is_quarantined
    assert results[0].record.rider_ref != results[2].record.rider_ref


def test_batch_survives_an_adapter_that_raises_on_a_bad_row() -> None:
    """Even if an adapter has a bug and raises instead of returning a
    quarantine, parse_batch must not let one row's exception kill the batch."""

    class _FlakyAdapter:
        def parse(self, raw_row: dict) -> AdapterResult:
            if raw_row.get("boom"):
                raise RuntimeError("simulated adapter bug")
            from app.canonical import Tenant, TenantId, new_id
            from conformance.fixtures.builders_connect import utc

            return AdapterResult(
                record=Tenant(tenant_id=new_id(TenantId), name="ok", created_at=utc(2026, 1, 1))
            )

    results = parse_batch(_FlakyAdapter(), [{"boom": False}, {"boom": True}, {"boom": False}])

    assert len(results) == 3
    assert not results[0].is_quarantined
    assert results[1].is_quarantined
    assert "RuntimeError" in results[1].quarantine.reason
    assert not results[2].is_quarantined


def test_adapter_result_rejects_both_record_and_quarantine_set_at_once() -> None:
    import pytest
    from pydantic import ValidationError

    from conformance.fixtures.builders import example_service_request, example_tenant

    tenant = example_tenant()
    request = example_service_request(tenant.tenant_id)

    with pytest.raises(ValidationError):
        AdapterResult(
            record=request,
            quarantine=QuarantinedRow(raw_row={"x": 1}, reason="should not coexist with a record"),
        )
