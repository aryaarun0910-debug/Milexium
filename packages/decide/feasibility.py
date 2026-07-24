"""Independent feasibility checker for a Decision solution (Program F, v0.1).

This is the Decide program's analogue of `packages.verify` vs
`packages.canonical`: a checker that validates a *proposed* `DecisionSolution`
against the hard constraints WITHOUT reusing any of the solver's search
reasoning. It imports the Decision IR and the canonical reason-code vocabulary
and nothing else -- crucially, it does NOT import `packages.decide.solver`. That
one-directional dependency (the solver may call the checker; the checker never
calls the solver) is what makes it a genuine independent verifier: it will
reject an infeasible assignment whether the solver produced it or a human
hand-wrote it, and a bug in the solver's own feasibility pruning cannot hide a
violation here because this module re-derives every constraint from the raw IR.

Scope, stated honestly: this checker verifies FEASIBILITY -- that no accepted
assignment breaks a hard constraint. It does NOT re-prove optimality; optimality
for this NP-hard problem cannot be independently certified in v0.1, so the
checker never blesses `objective_value`/`gap`. Its contract is exactly the one
blueprint 06 requires: no accepted result violates a hard constraint.

Structural malformedness (an assignment naming a request or vehicle not in the
problem, or the same request assigned twice / both served and denied) is raised
as `MalformedSolution`, not returned as a soft violation: such a solution is not
a valid answer *object* for this problem, a different failure from a well-formed
solution that breaks a hard constraint.
"""

from __future__ import annotations

from dataclasses import dataclass

from packages.canonical.vocab import ReasonCode
from packages.decide.ir import DecisionProblem, DecisionSolution, RideRequest


class MalformedSolution(ValueError):
    """The solution does not structurally correspond to the problem (unknown id,
    duplicate assignment, a request both served and denied)."""


@dataclass(frozen=True)
class Violation:
    code: ReasonCode
    detail: str
    request_id: str | None = None
    vehicle_id: str | None = None


def _minutes(start, end) -> float:
    return (end - start).total_seconds() / 60.0


def check_feasibility(problem: DecisionProblem, solution: DecisionSolution) -> list[Violation]:
    """Return every hard-constraint violation in `solution.assignments`. An empty
    list means the accepted assignments are feasible. Violations are returned,
    not raised, so one pass can enumerate all of them."""
    requests: dict[str, RideRequest] = {str(r.request_id): r for r in problem.requests}
    vehicles = {str(v.vehicle_id): v for v in problem.vehicles}

    _reject_malformed(problem, solution, requests, vehicles)

    violations: list[Violation] = []
    for a in solution.assignments:
        req = requests[str(a.request_id)]
        veh = vehicles[str(a.vehicle_id)]
        rid, vid = str(a.request_id), str(a.vehicle_id)

        # Precedence: a rider is picked up before being dropped off.
        if a.pickup_time >= a.dropoff_time:
            violations.append(Violation(ReasonCode.PRECEDENCE, f"pickup {a.pickup_time.isoformat()} not before dropoff {a.dropoff_time.isoformat()}", rid, vid))

        # Pickup window.
        if not (req.pickup_window_start <= a.pickup_time <= req.pickup_window_end):
            violations.append(Violation(ReasonCode.PICKUP_WINDOW, f"pickup {a.pickup_time.isoformat()} outside [{req.pickup_window_start.isoformat()}, {req.pickup_window_end.isoformat()}]", rid, vid))

        # Dropoff window (upper bound always; lower bound only if declared).
        if a.dropoff_time > req.dropoff_window_end:
            violations.append(Violation(ReasonCode.DROPOFF_WINDOW, f"dropoff {a.dropoff_time.isoformat()} after latest {req.dropoff_window_end.isoformat()}", rid, vid))
        if req.dropoff_window_start is not None and a.dropoff_time < req.dropoff_window_start:
            violations.append(Violation(ReasonCode.DROPOFF_WINDOW, f"dropoff {a.dropoff_time.isoformat()} before earliest {req.dropoff_window_start.isoformat()}", rid, vid))

        # Max ride time.
        ride = _minutes(a.pickup_time, a.dropoff_time)
        if ride > req.max_ride_time_minutes:
            violations.append(Violation(ReasonCode.MAX_RIDE_TIME, f"ride {ride:.1f}min exceeds max {req.max_ride_time_minutes:.1f}min", rid, vid))

        # Shift containment.
        if a.pickup_time < veh.shift_start or a.dropoff_time > veh.shift_end:
            violations.append(Violation(ReasonCode.SHIFT_END, f"trip [{a.pickup_time.isoformat()}, {a.dropoff_time.isoformat()}] outside shift [{veh.shift_start.isoformat()}, {veh.shift_end.isoformat()}]", rid, vid))

        # Wheelchair rider on a vehicle with no wheelchair position.
        if req.needs_wheelchair and veh.capacity_wheelchair < 1:
            violations.append(Violation(ReasonCode.NO_ACCESSIBLE_CAPACITY, "wheelchair request on a vehicle with no wheelchair capacity", rid, vid))

    violations.extend(_capacity_violations(problem, solution, requests, vehicles))
    return violations


def _reject_malformed(problem, solution, requests, vehicles) -> None:
    served: set[str] = set()
    for a in solution.assignments:
        if str(a.request_id) not in requests:
            raise MalformedSolution(f"assignment references unknown request {a.request_id}")
        if str(a.vehicle_id) not in vehicles:
            raise MalformedSolution(f"assignment references unknown vehicle {a.vehicle_id}")
        if str(a.request_id) in served:
            raise MalformedSolution(f"request {a.request_id} assigned more than once")
        served.add(str(a.request_id))
    for d in solution.unserved:
        if str(d.request_id) not in requests:
            raise MalformedSolution(f"denial references unknown request {d.request_id}")
        if str(d.request_id) in served:
            raise MalformedSolution(f"request {d.request_id} is both served and denied")


def _capacity_violations(problem, solution, requests, vehicles) -> list[Violation]:
    """Sweep-line the onboard load per vehicle and reason-code any interval where
    concurrent riders exceed capacity for their type. Re-derived here from the
    assigned times -- the checker never trusts the solver's own load bookkeeping."""
    violations: list[Violation] = []
    by_vehicle: dict[str, list] = {}
    for a in solution.assignments:
        by_vehicle.setdefault(str(a.vehicle_id), []).append(a)

    for vid, assigns in by_vehicle.items():
        veh = vehicles[vid]
        # A boundary event at each pickup (+load) and dropoff (-load), per type.
        for cap_type, capacity in (("wheelchair", veh.capacity_wheelchair), ("ambulatory", veh.capacity_ambulatory)):
            events: list[tuple] = []
            for a in assigns:
                req = requests[str(a.request_id)]
                is_wc = req.needs_wheelchair
                if cap_type == "wheelchair" and not is_wc:
                    continue
                if cap_type == "ambulatory" and is_wc:
                    continue
                load = 1 if is_wc else req.party_size
                # A dropoff frees capacity the instant it happens; order -1 before +1 at equal times.
                events.append((a.pickup_time, 1, load, str(a.request_id)))
                events.append((a.dropoff_time, 0, -load, str(a.request_id)))
            events.sort(key=lambda e: (e[0], e[1]))
            onboard = 0
            for _time, _kind, delta, rid in events:
                onboard += delta
                if onboard > capacity:
                    violations.append(Violation(ReasonCode.NO_ACCESSIBLE_CAPACITY, f"{cap_type} load {onboard} exceeds capacity {capacity} on vehicle {vid}", rid, vid))
    return violations


def is_feasible(problem: DecisionProblem, solution: DecisionSolution) -> bool:
    """True iff no accepted assignment breaks a hard constraint. Raises
    `MalformedSolution` for a structurally invalid solution -- an unknown id is a
    caller error, not a feasibility verdict."""
    return not check_feasibility(problem, solution)
