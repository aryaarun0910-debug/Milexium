"""Property tests for the ServiceRequest state machine (Program A contract).

Exhaustive over the full state x state grid (8x8 = 64 pairs) rather than a
handful of examples, so a future edit to `SERVICE_REQUEST_TRANSITIONS` that
accidentally legalizes an unintended transition fails a test immediately.
"""

from __future__ import annotations

import itertools

import pytest

from packages.canonical.state_machine import (
    ILLEGAL_TRANSITIONS_EXAMPLE,
    SERVICE_REQUEST_TRANSITIONS,
    ServiceRequestState,
    TransitionError,
    check_transition,
)
from packages.verify import verify_state_sequence

ALL_STATES = list(ServiceRequestState)
ALL_PAIRS = list(itertools.product(ALL_STATES, ALL_STATES))


@pytest.mark.parametrize("current,target", ALL_PAIRS)
def test_transition_matches_contract_table(current: ServiceRequestState, target: ServiceRequestState) -> None:
    allowed = target in SERVICE_REQUEST_TRANSITIONS.get(current, frozenset())
    if allowed:
        check_transition(current, target)  # must not raise
    else:
        with pytest.raises(TransitionError):
            check_transition(current, target)


def test_no_self_loops() -> None:
    """A state can never legally transition to itself -- this is what makes a
    duplicate command idempotent-rejectable rather than silently re-applied."""
    for state in ALL_STATES:
        assert state not in SERVICE_REQUEST_TRANSITIONS.get(state, frozenset())


def test_terminal_states_have_no_outgoing_transitions() -> None:
    terminal = {
        ServiceRequestState.COMPLETED,
        ServiceRequestState.DENIED,
        ServiceRequestState.CANCELLED,
        ServiceRequestState.NO_SHOW,
    }
    for state in terminal:
        assert SERVICE_REQUEST_TRANSITIONS[state] == frozenset()


def test_illegal_transitions_example_is_actually_illegal() -> None:
    current, target = ILLEGAL_TRANSITIONS_EXAMPLE
    with pytest.raises(TransitionError):
        check_transition(current, target)


def test_independent_state_verifier_agrees_with_check_transition() -> None:
    """The independent verifier (packages/verify) must reach the same verdict
    as the generator-side check_transition on every pair -- this is the
    property that proves they were not implemented as one function pretending
    to be two."""
    for current, target in ALL_PAIRS:
        violations = verify_state_sequence("req-example", [current, target])
        contract_says_legal = target in SERVICE_REQUEST_TRANSITIONS.get(current, frozenset())
        verifier_says_legal = len(violations) == 0
        assert contract_says_legal == verifier_says_legal, (current, target)


def test_verifier_catches_a_full_illegal_history() -> None:
    history = [
        ServiceRequestState.REQUESTED,
        ServiceRequestState.NEGOTIATED,
        ServiceRequestState.SCHEDULED,
        ServiceRequestState.IN_PROGRESS,
        ServiceRequestState.COMPLETED,
        ServiceRequestState.REQUESTED,  # illegal: COMPLETED is terminal
    ]
    violations = verify_state_sequence("req-example", history)
    assert len(violations) == 1
    assert violations[0].from_version == 5
    assert violations[0].to_version == 6
