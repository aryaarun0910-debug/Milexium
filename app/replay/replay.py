"""Program H (partial): historical replay respecting information cutoffs.

The integrity core of replay. A replayed decision must only ever see facts
that had actually occurred by the replay instant -- no future information
leaking backward, the first technical failure mode this program guards against.
This module reconstructs "what was known as of the replay instant" strictly by
delegating to app.canonical.time.RequestTimes.known_as_of (the canonical,
tested cutoff rule) rather than re-implementing a weaker one, and raises
ReplayError when a caller-supplied replay input still carries a fact from the
future.

Nothing here claims causation: reconstructing the inputs a decision saw is a
faithfulness property (it saw exactly this and no more), not evidence that the
decision was good. The baseline-vs-Milexium scoring built on top of it
(app.replay.comparison) is likewise a *modelled comparison, not causal
proof of savings* (see that module).
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from app.canonical.entities import ServiceRequest
from app.canonical.time import RequestTimes

# The RequestTimes fields known_as_of may hide -- kept in one place so this
# module's leak check and the canonical cutoff rule can never silently diverge.
_FUTURE_MASKABLE_FIELDS: tuple[str, ...] = (
    "negotiated_window_start",
    "negotiated_window_end",
    "scheduled_pickup_at",
    "predicted_pickup_at",
    "actual_pickup_at",
)


class ReplayError(Exception):
    """Raised when a replay would use information that did not exist yet at the
    replay instant (future-information leakage)."""


def known_as_of_request(request: ServiceRequest, instant: datetime) -> ServiceRequest:
    """Return a copy of `request` whose times are masked to the replay instant.

    Delegates the cutoff to RequestTimes.known_as_of so the replay obeys exactly
    the canonical rule; a correction is never mutated (model_copy makes a new
    frozen object).
    """
    return request.model_copy(update={"times": request.times.known_as_of(instant)})


def replay_requests_as_of(
    requests: Iterable[ServiceRequest], instant: datetime
) -> tuple[ServiceRequest, ...]:
    """Reconstruct the request set as it was knowable at `instant`.

    This is safe by construction: every returned request has had future time
    fields hidden, so a decision replayed over the result cannot see the future.
    """
    return tuple(known_as_of_request(request, instant) for request in requests)


def _leaked_fields(times: RequestTimes, instant: datetime) -> tuple[str, ...]:
    """Fields known_as_of would have hidden -- i.e. facts from after `instant`.

    Defined as "what the canonical cutoff would mask" so the leak definition is
    the cutoff rule itself, not a second copy of it. known_as_of also validates
    that `instant` is UTC-aware, so callers get that check for free.
    """
    masked = times.known_as_of(instant)
    if masked == times:
        return ()
    return tuple(
        name
        for name in _FUTURE_MASKABLE_FIELDS
        if getattr(times, name) != getattr(masked, name)
    )


def verify_no_future_leak(times: RequestTimes, instant: datetime) -> None:
    """Raise ReplayError if `times` carries any fact from after the replay instant.

    Use this to validate an externally-supplied "as of" state (one that was NOT
    produced by replay_requests_as_of) before feeding it to a replayed decision:
    it catches the case where a caller forgot to apply the cutoff, or injected a
    future value.
    """
    leaked = _leaked_fields(times, instant)
    if leaked:
        raise ReplayError(
            f"replay input leaks future information as of {instant.isoformat()}: "
            f"fields {leaked} carry timestamps after the replay instant"
        )


def assert_requests_known_as_of(
    requests: Iterable[ServiceRequest], instant: datetime
) -> None:
    """Raise ReplayError on the first request that leaks a future fact at `instant`."""
    for request in requests:
        try:
            verify_no_future_leak(request.times, instant)
        except ReplayError as exc:
            raise ReplayError(f"request {request.request_id}: {exc}") from exc
