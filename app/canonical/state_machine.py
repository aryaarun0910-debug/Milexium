"""ServiceRequest state machine (Program A: "domain state machines and
idempotent commands").

This table is the normative contract for legal transitions. Any component
that wants to move a request between states -- the roadmap's scheduler, the
expansion's Decide/Verify programs -- checks against this table; none of them
own a private copy of it.
"""

from __future__ import annotations

from enum import Enum


class ServiceRequestState(str, Enum):
    REQUESTED = "requested"
    NEGOTIATED = "negotiated"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    DENIED = "denied"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


SERVICE_REQUEST_TRANSITIONS: dict[ServiceRequestState, frozenset[ServiceRequestState]] = {
    ServiceRequestState.REQUESTED: frozenset(
        {ServiceRequestState.NEGOTIATED, ServiceRequestState.DENIED, ServiceRequestState.CANCELLED}
    ),
    ServiceRequestState.NEGOTIATED: frozenset(
        {ServiceRequestState.SCHEDULED, ServiceRequestState.DENIED, ServiceRequestState.CANCELLED}
    ),
    ServiceRequestState.SCHEDULED: frozenset(
        {ServiceRequestState.IN_PROGRESS, ServiceRequestState.CANCELLED, ServiceRequestState.NO_SHOW}
    ),
    ServiceRequestState.IN_PROGRESS: frozenset({ServiceRequestState.COMPLETED}),
    ServiceRequestState.COMPLETED: frozenset(),
    ServiceRequestState.DENIED: frozenset(),
    ServiceRequestState.CANCELLED: frozenset(),
    ServiceRequestState.NO_SHOW: frozenset(),
}
"""Terminal states (empty transition sets): COMPLETED, DENIED, CANCELLED, NO_SHOW."""


def _derive_initial_state() -> ServiceRequestState:
    """The one state no legal transition can ever ARRIVE at.

    DERIVED from the table above rather than declared beside it, so the two can
    never disagree. A second declaration would be a second place for the same
    fact to drift, and the durable lifecycle record (`lifecycle.py`) anchors
    every request's chain on this value -- if it silently stopped matching the
    table, every chain would start in the wrong place and still look legal.
    """
    reachable = {
        target for targets in SERVICE_REQUEST_TRANSITIONS.values() for target in targets
    }
    roots = [state for state in SERVICE_REQUEST_TRANSITIONS if state not in reachable]
    if len(roots) != 1:  # pragma: no cover - guarded by test_state_machine_anchors.py
        raise AssertionError(
            f"the transition table must have exactly one entry state, found {roots!r}"
        )
    return roots[0]


SERVICE_REQUEST_INITIAL_STATE: ServiceRequestState = _derive_initial_state()
"""The state every ServiceRequest begins in (REQUESTED), derived from the table."""

SERVICE_REQUEST_TERMINAL_STATES: frozenset[ServiceRequestState] = frozenset(
    state for state, targets in SERVICE_REQUEST_TRANSITIONS.items() if not targets
)
"""The states with no outgoing transition, derived from the table."""


class TransitionError(ValueError):
    """Raised when a requested state transition is not in the contract table."""


def check_transition(current: ServiceRequestState, target: ServiceRequestState) -> None:
    """Raise TransitionError if `current -> target` is not a legal transition.

    Idempotent by construction: calling this with `current == target` is
    always illegal (no self-loop in the table above), so a duplicate command
    that tries to re-apply an already-applied transition is rejected here
    rather than silently accepted twice.
    """
    allowed = SERVICE_REQUEST_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        allowed_names = sorted(s.value for s in allowed) or ["<none: terminal state>"]
        raise TransitionError(
            f"illegal transition {current.value!r} -> {target.value!r}; "
            f"allowed targets from {current.value!r}: {allowed_names}"
        )


ILLEGAL_TRANSITIONS_EXAMPLE = (ServiceRequestState.COMPLETED, ServiceRequestState.REQUESTED)
"""A concrete counterexample: COMPLETED is terminal, so this must always raise.

Referenced by evidence/conformance/fixtures and app/verify so both the fixture
author and the independent verifier agree on at least one ground-truth
illegal case without duplicating the reasoning.
"""
