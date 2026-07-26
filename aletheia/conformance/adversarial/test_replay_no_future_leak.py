"""Replay information-cutoff integrity (Program H, adversarial).

The first technical failure mode a replay must resist is future information
leaking backward: a decision replayed "as of" an earlier instant seeing a fact
that was only known later. These tests prove the replay reconstruction hides an
actual_pickup_at that occurred after the replay instant, and that an explicit
leak in a caller-supplied replay input is rejected with ReplayError rather than
silently used.
"""

from __future__ import annotations

import pytest

from themis.canonical import RequestTimes
from aletheia.replay import (
    ReplayError,
    assert_requests_known_as_of,
    known_as_of_request,
    replay_requests_as_of,
    verify_no_future_leak,
)

from conformance.fixtures.builders import example_tenant, utc
from conformance.fixtures.builders_replay import make_request_with_actual_pickup


def test_replay_hides_actual_pickup_that_happened_after_the_instant() -> None:
    tenant = example_tenant()
    # The trip actually completed at 08:17; a replay standing at 08:16 (just
    # after scheduling, before the trip) must not see that future fact.
    request = make_request_with_actual_pickup(
        tenant.tenant_id,
        actual_pickup_at=utc(2026, 7, 23, 8, 17),
        scheduled_pickup_at=utc(2026, 7, 23, 8, 15),
    )
    (replayed,) = replay_requests_as_of([request], utc(2026, 7, 23, 8, 16))

    assert replayed.times.actual_pickup_at is None  # future fact hidden
    assert replayed.times.scheduled_pickup_at == utc(2026, 7, 23, 8, 15)  # known, kept
    assert request.times.actual_pickup_at == utc(2026, 7, 23, 8, 17)  # original untouched


def test_replay_after_the_trip_sees_the_actual_pickup() -> None:
    tenant = example_tenant()
    request = make_request_with_actual_pickup(
        tenant.tenant_id, actual_pickup_at=utc(2026, 7, 23, 8, 17)
    )
    replayed = known_as_of_request(request, utc(2026, 7, 23, 9, 0))
    assert replayed.times.actual_pickup_at == utc(2026, 7, 23, 8, 17)


def test_verify_no_future_leak_rejects_a_future_fact() -> None:
    times = RequestTimes(
        requested_at=utc(2026, 7, 23, 8, 0),
        actual_pickup_at=utc(2026, 7, 23, 8, 17),
    )
    with pytest.raises(ReplayError):
        verify_no_future_leak(times, utc(2026, 7, 23, 8, 16))


def test_verify_no_future_leak_passes_a_clean_cutoff_state() -> None:
    times = RequestTimes(
        requested_at=utc(2026, 7, 23, 8, 0),
        scheduled_pickup_at=utc(2026, 7, 23, 8, 15),
    )
    # Nothing after the instant -- must not raise.
    verify_no_future_leak(times, utc(2026, 7, 23, 8, 16))


def test_replay_output_never_leaks_and_re_verifies_clean() -> None:
    tenant = example_tenant()
    request = make_request_with_actual_pickup(
        tenant.tenant_id, actual_pickup_at=utc(2026, 7, 23, 8, 17)
    )
    instant = utc(2026, 7, 23, 8, 16)
    replayed = replay_requests_as_of([request], instant)
    # The masked reconstruction passes the same leak check that would have
    # rejected the raw request -- safe by construction.
    assert_requests_known_as_of(replayed, instant)


def test_assert_requests_known_as_of_flags_a_leaking_request() -> None:
    tenant = example_tenant()
    leaking = make_request_with_actual_pickup(
        tenant.tenant_id, actual_pickup_at=utc(2026, 7, 23, 8, 17)
    )
    with pytest.raises(ReplayError):
        assert_requests_known_as_of([leaking], utc(2026, 7, 23, 8, 16))
