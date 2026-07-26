"""Bitemporal correction properties (Program A: "bitemporal records and
immutable corrections", blueprint/14-execution-roadmap.md Program A).

A correction must produce a *new* version referencing the one it corrects,
never mutate the original -- and a replay reading "as of" an earlier instant
must not see facts that were only known later (no future leakage, the first
technical failure mode listed in blueprint/15-risks-and-falsification.md).
"""

from __future__ import annotations

from datetime import datetime, timezone

from themis.canonical import BitemporalMeta, RequestTimes, ServiceRequestState

from conformance.fixtures.builders import example_service_request, example_tenant, utc


def test_correction_creates_new_version_referencing_the_original() -> None:
    tenant = example_tenant()
    original = example_service_request(tenant.tenant_id, version=1)
    assert not original.meta.is_correction()

    corrected = example_service_request(
        tenant.tenant_id,
        request_id=original.request_id,
        status=ServiceRequestState.NEGOTIATED,
        version=2,
        corrects_version=1,
    )
    assert corrected.request_id == original.request_id
    assert corrected.meta.is_correction()
    assert corrected.meta.corrects_version == 1
    # The original object itself is untouched -- Pydantic frozen model would
    # raise on any attempted mutation, but the real invariant is architectural:
    # nothing in themis/canonical ever calls .model_copy(update=...) on a
    # persisted version. Storage only ever INSERTs a new (request_id, version)
    # row (schema_v0_1.sql primary key is a composite of both).
    assert original.status == ServiceRequestState.REQUESTED
    assert original.meta.version == 1


def test_known_as_of_hides_future_information() -> None:
    times = RequestTimes(
        requested_at=utc(2026, 7, 23, 8, 0),
        negotiated_window_start=utc(2026, 7, 23, 8, 10),
        negotiated_window_end=utc(2026, 7, 23, 8, 25),
        scheduled_pickup_at=utc(2026, 7, 23, 8, 15),
        predicted_pickup_at=utc(2026, 7, 23, 8, 14),
        actual_pickup_at=utc(2026, 7, 23, 8, 17),  # only known after the trip happened
    )

    # A replay running "as of" right after scheduling, before the trip
    # actually occurred, must not see actual_pickup_at.
    as_of_scheduling = times.known_as_of(utc(2026, 7, 23, 8, 16))
    assert as_of_scheduling.actual_pickup_at is None
    assert as_of_scheduling.scheduled_pickup_at == utc(2026, 7, 23, 8, 15)

    # A replay running after the trip happened sees everything.
    as_of_after = times.known_as_of(utc(2026, 7, 23, 9, 0))
    assert as_of_after.actual_pickup_at == utc(2026, 7, 23, 8, 17)


def test_known_as_of_at_the_exact_instant_is_inclusive() -> None:
    times = RequestTimes(
        requested_at=utc(2026, 7, 23, 8, 0),
        actual_pickup_at=utc(2026, 7, 23, 8, 17),
    )
    as_of_exact = times.known_as_of(utc(2026, 7, 23, 8, 17))
    assert as_of_exact.actual_pickup_at == utc(2026, 7, 23, 8, 17)


def test_requires_timezone_aware_utc_timestamps() -> None:
    import pytest

    with pytest.raises(ValueError):
        RequestTimes(requested_at=datetime(2026, 7, 23, 8, 0))  # naive datetime, no tz

    with pytest.raises(ValueError):
        from datetime import timedelta

        RequestTimes(
            requested_at=datetime(2026, 7, 23, 8, 0, tzinfo=timezone(timedelta(hours=-7)))
        )  # non-UTC offset
