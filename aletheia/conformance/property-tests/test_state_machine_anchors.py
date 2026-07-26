"""Property tests for the two DERIVED anchors on the ServiceRequest contract
table: the entry state and the terminal set (MX-A-LIFECYCLE-RECORD-010).

WHY THESE EXIST AT ALL. The durable lifecycle record needs two facts the
transition table has always implied but never named: where a chain must START,
and where a chain may END. `themis/canonical/lifecycle.py` anchors every
request's history on the first and reports the second as the outcome.

They are DERIVED from `SERVICE_REQUEST_TRANSITIONS` rather than declared beside
it, deliberately -- a second declaration would be a second place for the same
fact to drift, and the drift would be silent in the worst possible way: every
chain would start at the wrong state and every individual transition in it would
still be legal. These tests pin the derivation against the literal answer in both
directions, so a table edit that moved the entry state has to be a decision
someone makes here rather than a consequence nobody notices.

`test_state_transitions.py` covers the table's own content (the 8x8 grid, the
no-self-loop rule, the independent verifier's agreement). This file covers only
what the lifecycle record newly depends on.
"""

from __future__ import annotations

from themis.canonical.state_machine import (
    SERVICE_REQUEST_INITIAL_STATE,
    SERVICE_REQUEST_TERMINAL_STATES,
    SERVICE_REQUEST_TRANSITIONS,
    ServiceRequestState,
    _derive_initial_state,
)


def test_the_entry_state_is_requested() -> None:
    """The literal answer, pinned. If a future table edit made some other state
    unreachable, the derivation would happily return that instead and every
    lifecycle chain would silently be anchored somewhere new."""
    assert SERVICE_REQUEST_INITIAL_STATE is ServiceRequestState.REQUESTED


def test_the_entry_state_is_the_only_state_nothing_can_transition_into() -> None:
    """The derivation's own definition, checked against the table independently of
    the function that computes it -- so this is not the derivation agreeing with
    itself."""
    reachable = {
        target for targets in SERVICE_REQUEST_TRANSITIONS.values() for target in targets
    }
    unreachable = {state for state in ServiceRequestState if state not in reachable}

    assert unreachable == {SERVICE_REQUEST_INITIAL_STATE}
    assert SERVICE_REQUEST_INITIAL_STATE not in reachable


def test_the_derivation_refuses_a_table_with_no_single_entry_state() -> None:
    """The failure branch, exercised rather than assumed reachable.

    A table with two unreachable states has no single place a chain can start, and
    a table with none is a cycle with no beginning. Both are contract bugs, and
    the derivation must raise rather than silently pick one -- this repository has
    already found a test asserting an unreachable branch, so a guard clause nobody
    can trigger is not evidence of anything."""
    import themis.canonical.state_machine as state_machine

    original = state_machine.SERVICE_REQUEST_TRANSITIONS
    try:
        # Two entry states: nothing transitions into REQUESTED or into CANCELLED.
        state_machine.SERVICE_REQUEST_TRANSITIONS = {
            ServiceRequestState.REQUESTED: frozenset({ServiceRequestState.DENIED}),
            ServiceRequestState.CANCELLED: frozenset({ServiceRequestState.DENIED}),
            ServiceRequestState.DENIED: frozenset(),
        }
        raised = None
        try:
            _derive_initial_state()
        except AssertionError as error:  # noqa: PT017 - the type IS the assertion here
            raised = error
        assert raised is not None, "a table with two entry states was accepted"
        assert "exactly one entry state" in str(raised)

        # And a table with none (a pure cycle) is refused for the same reason.
        state_machine.SERVICE_REQUEST_TRANSITIONS = {
            ServiceRequestState.REQUESTED: frozenset({ServiceRequestState.NEGOTIATED}),
            ServiceRequestState.NEGOTIATED: frozenset({ServiceRequestState.REQUESTED}),
        }
        raised = None
        try:
            _derive_initial_state()
        except AssertionError as error:  # noqa: PT017
            raised = error
        assert raised is not None, "a table with no entry state was accepted"
    finally:
        state_machine.SERVICE_REQUEST_TRANSITIONS = original

    # The module is left exactly as it was found -- the real derivation still
    # answers correctly after the monkey-patching above.
    assert _derive_initial_state() is ServiceRequestState.REQUESTED


def test_the_terminal_set_is_the_four_outcomes() -> None:
    """The literal answer, pinned. These four are what "the outcome a trip
    received" can be, and the lifecycle record's explain view reports exactly this
    set as terminal."""
    assert SERVICE_REQUEST_TERMINAL_STATES == frozenset(
        {
            ServiceRequestState.COMPLETED,
            ServiceRequestState.DENIED,
            ServiceRequestState.CANCELLED,
            ServiceRequestState.NO_SHOW,
        }
    )


def test_the_terminal_set_is_exactly_the_states_with_no_outgoing_transition() -> None:
    """Derived-vs-literal in the other direction: every state with an empty
    allowed set is terminal, and every terminal state has an empty allowed set."""
    for state in ServiceRequestState:
        has_outgoing = bool(SERVICE_REQUEST_TRANSITIONS[state])
        assert (state in SERVICE_REQUEST_TERMINAL_STATES) is not has_outgoing, state


def test_the_entry_state_is_not_itself_terminal() -> None:
    """A machine whose entry state were also terminal could record no history at
    all -- every chain would be empty and the record would be vacuous while
    looking complete."""
    assert SERVICE_REQUEST_INITIAL_STATE not in SERVICE_REQUEST_TERMINAL_STATES
    assert SERVICE_REQUEST_TRANSITIONS[SERVICE_REQUEST_INITIAL_STATE]
