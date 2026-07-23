"""Adversarial fixtures for packages/connect/tlc_trips.py: malformed or
low-signal real-world FHVHV rows must be quarantined with a clear reason --
never silently dropped, never an uncaught exception that kills the batch
(blueprint/03-connect-and-standards.md mapping rule 7: "quarantine
impossible or policy-sensitive records rather than guessing"). Both failure
modes below are real, observed conditions in realdata/raw_tlc/
fhvhv_tripdata_2019-02.parquet (108,898 null request_datetime rows and
601,365 unknown-dropoff-zone rows out of 20,159,102), not hypotheticals.
"""

from __future__ import annotations

from packages.connect.adapter import QuarantinedRow, parse_batch

from conformance.fixtures.builders_connect_tlc import example_tlc_adapter, example_tlc_row


def test_row_missing_required_request_datetime_is_quarantined_not_dropped() -> None:
    """Real, observed failure mode: request_datetime is null for ~0.5% of
    rows in fhvhv_tripdata_2019-02.parquet."""

    adapter, _ = example_tlc_adapter()
    row = example_tlc_row(request_datetime=None)

    result = adapter.parse(row)

    assert result.is_quarantined
    assert result.record is None
    assert result.semantic_loss == ()
    assert isinstance(result.quarantine, QuarantinedRow)
    assert "request_datetime" in result.quarantine.reason
    assert result.quarantine.failed_field == "request_datetime"
    assert result.quarantine.raw_row["PULocationID"] == 245  # original row preserved for re-run


def test_unknown_pickup_zone_code_is_quarantined_not_silently_accepted() -> None:
    """Real, observed failure mode: TLC's own 264/265 placeholder location
    ids ("unknown"/"outside of NYC") are not real geographic zones."""

    adapter, _ = example_tlc_adapter()
    row = example_tlc_row(PULocationID=264)

    result = adapter.parse(row)

    assert result.is_quarantined
    assert "264" in result.quarantine.reason
    assert "PULocationID" in result.quarantine.reason


def test_unknown_dropoff_zone_code_is_quarantined_not_silently_accepted() -> None:
    adapter, _ = example_tlc_adapter()
    row = example_tlc_row(DOLocationID=265)

    result = adapter.parse(row)

    assert result.is_quarantined
    assert "265" in result.quarantine.reason
    assert "DOLocationID" in result.quarantine.reason


def test_row_with_invalid_wav_request_flag_value_is_quarantined_with_a_clear_reason() -> None:
    adapter, _ = example_tlc_adapter()
    row = example_tlc_row(wav_request_flag="maybe")

    result = adapter.parse(row)

    assert result.is_quarantined
    assert "maybe" in result.quarantine.reason
    assert "wav_request_flag" in result.quarantine.reason


def test_batch_with_one_bad_row_quarantines_only_that_row() -> None:
    adapter, _ = example_tlc_adapter()
    rows = [
        example_tlc_row(PULocationID=100),
        example_tlc_row(PULocationID=101, request_datetime=None),
        example_tlc_row(PULocationID=102),
    ]

    results = parse_batch(adapter, rows)

    assert len(results) == 3
    assert not results[0].is_quarantined
    assert results[1].is_quarantined
    assert not results[2].is_quarantined
    assert results[0].record.rider_ref != results[2].record.rider_ref
