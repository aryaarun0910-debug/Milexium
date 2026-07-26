"""Independent state-machine verifier for ServiceRequest version histories.

Reads the same `SERVICE_REQUEST_TRANSITIONS` table that
`app.canonical.state_machine.check_transition` uses -- that table *is*
the normative contract (knowledge/architecture/contracts/), so both the writer and this
verifier consulting it is correct, not circular. What this module does not do
is call `check_transition` itself or trust that a caller only ever produced
legal versions; it re-derives legality from the full version history that
would actually be in storage.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.canonical.state_machine import SERVICE_REQUEST_TRANSITIONS, ServiceRequestState


@dataclass(frozen=True)
class StateViolation:
    request_id: str
    from_version: int
    to_version: int
    detail: str


def verify_state_sequence(
    request_id: str, ordered_statuses: list[ServiceRequestState]
) -> list[StateViolation]:
    """`ordered_statuses`: the `status` of each version of one ServiceRequest,
    version 1 first. Returns every illegal consecutive transition found."""
    violations: list[StateViolation] = []
    for i in range(1, len(ordered_statuses)):
        prev_state = ordered_statuses[i - 1]
        next_state = ordered_statuses[i]
        allowed = SERVICE_REQUEST_TRANSITIONS.get(prev_state, frozenset())
        if next_state not in allowed:
            violations.append(
                StateViolation(
                    request_id=request_id,
                    from_version=i,
                    to_version=i + 1,
                    detail=f"{prev_state.value} -> {next_state.value} is not a legal transition",
                )
            )
    return violations
