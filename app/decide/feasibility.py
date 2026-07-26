"""Independent feasibility checker for a Decision solution (Program F, v0.1).

This is the Decide program's analogue of `app.verify` vs
`app.canonical`: a checker that validates a *proposed* `DecisionSolution`
against the hard constraints WITHOUT reusing any of the solver's search
reasoning. It imports the Decision IR and the canonical reason-code vocabulary
and nothing else -- crucially, it does NOT import `app.decide.solver`. That
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

from app.canonical.vocab import ReasonCode
from app.decide.ir import DecisionProblem, DecisionSolution, RideRequest


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


# ==========================================================================
# DARP feasibility checker (Program F v0.2 -- routing extension)
#
# The independent checker for a *routed, scheduled* dial-a-ride solution. Same
# discipline as `check_feasibility` above: it imports only the DARP IR and the
# canonical reason-code vocabulary -- never `app.decide.darp_solver`. It
# re-derives every hard DARP constraint from the raw instance and the concrete
# begin-service times the solution commits to, so it will reject an infeasible
# routing whoever produced it, and no scheduling bug in a solver can hide a
# violation here. It verifies FEASIBILITY only; it never certifies optimality,
# and it independently *recomputes* the objective rather than trusting the
# solver's reported number.
# ==========================================================================

from app.decide.darp_ir import DarpInstance, DarpSolution  # noqa: E402

_DARP_EPS = 1e-6  # forgive floating-point noise only; far tighter than any solver margin.


class MalformedDarpSolution(ValueError):
    """The routed solution is not a structurally valid answer for the instance
    (a node index out of range, a node visited more than once, or a route that
    does not begin and end at the depot)."""


@dataclass(frozen=True)
class DarpViolation:
    code: ReasonCode
    detail: str
    vehicle: int | None = None
    node_index: int | None = None
    request: int | None = None


def darp_served_requests(instance: DarpInstance, solution: DarpSolution) -> set[int]:
    """The set of request ids (1..n) whose pickup node appears in some route.
    Derived from the routes, never trusting `solution.served_requests`."""
    served: set[int] = set()
    for route in solution.routes:
        for v in route.visits:
            if instance.is_pickup(v.node_index):
                served.add(instance.request_of(v.node_index))
    return served


def darp_objective(instance: DarpInstance, solution: DarpSolution) -> float:
    """Independently recompute total routing distance (the standard DARP
    objective) from the routes, summing Euclidean arc lengths. The harness uses
    THIS value for gap reporting -- the solver's self-reported objective is never
    trusted for the benchmark number."""
    total = 0.0
    for route in solution.routes:
        seq = route.node_sequence()
        for a, b in zip(seq, seq[1:]):
            total += instance.dist(a, b)
    return total


def check_darp_feasibility(instance: DarpInstance, solution: DarpSolution) -> list[DarpViolation]:
    """Return every hard-constraint violation in `solution`. An empty list means
    the routed schedule is feasible for `instance` (for the requests it serves;
    leaving a request entirely unserved is not itself a violation, but a request
    that is picked up and not dropped off, or vice versa, is).

    Raises `MalformedDarpSolution` for a structurally invalid answer (out-of-range
    node, a node served twice, a route not anchored at the depot)."""
    n = instance.num_requests
    depot_ids = {instance.depot_start, instance.depot_end}
    _reject_malformed_darp(instance, solution, n, depot_ids)

    violations: list[DarpViolation] = []

    # Fleet size: no more routes than vehicles.
    non_empty = [r for r in solution.routes if any(v.node_index not in depot_ids for v in r.visits)]
    if len(non_empty) > instance.num_vehicles:
        violations.append(
            DarpViolation(ReasonCode.SHIFT_END, f"{len(non_empty)} routes used but only {instance.num_vehicles} vehicles available")
        )

    for route in solution.routes:
        violations.extend(_check_route(instance, route, depot_ids))

    # Pairing: each served request's pickup and drop-off must be on the SAME
    # route with the pickup visited before the drop-off. (Cross-route or
    # half-served requests are precedence violations.)
    violations.extend(_check_pairing(instance, solution, n))
    return violations


def _reject_malformed_darp(instance, solution, n, depot_ids) -> None:
    seen: set[int] = set()
    for route in solution.routes:
        if not route.visits:
            raise MalformedDarpSolution(f"vehicle {route.vehicle}: empty route (no depot anchors)")
        first, last = route.visits[0].node_index, route.visits[-1].node_index
        if first not in depot_ids or last not in depot_ids:
            raise MalformedDarpSolution(
                f"vehicle {route.vehicle}: route must begin and end at the depot, "
                f"got nodes {first}..{last}"
            )
        for v in route.visits:
            if not (0 <= v.node_index <= 2 * n + 1):
                raise MalformedDarpSolution(f"vehicle {route.vehicle}: node index {v.node_index} out of range")
            if v.node_index in depot_ids:
                continue
            if v.node_index in seen:
                raise MalformedDarpSolution(f"node {v.node_index} visited more than once")
            seen.add(v.node_index)


def _check_route(instance: DarpInstance, route, depot_ids) -> list[DarpViolation]:
    out: list[DarpViolation] = []
    visits = route.visits
    nodes = instance.nodes

    # Time windows at every visit; depot windows map to SHIFT_END.
    for v in visits:
        nd = nodes[v.node_index]
        if v.begin_service < nd.tw_start - _DARP_EPS or v.begin_service > nd.tw_end + _DARP_EPS:
            if v.node_index in depot_ids:
                code = ReasonCode.SHIFT_END
            elif instance.is_pickup(v.node_index):
                code = ReasonCode.PICKUP_WINDOW
            else:
                code = ReasonCode.DROPOFF_WINDOW
            out.append(DarpViolation(code, f"begin-service {v.begin_service:.4f} outside window [{nd.tw_start:.1f}, {nd.tw_end:.1f}]", route.vehicle, v.node_index))

    # Travel-time consistency: you cannot begin service at the next stop before
    # you could have finished service here and driven there.
    for u, w in zip(visits, visits[1:]):
        nu = nodes[u.node_index]
        earliest_next = u.begin_service + nu.service_duration + instance.dist(u.node_index, w.node_index)
        if w.begin_service < earliest_next - _DARP_EPS:
            out.append(DarpViolation(ReasonCode.PRECEDENCE, f"begin-service {w.begin_service:.4f} at node {w.node_index} precedes earliest reachable {earliest_next:.4f} from node {u.node_index}", route.vehicle, w.node_index))

    # Capacity: sweep the signed load in visit order.
    load = 0
    for v in visits:
        load += nodes[v.node_index].load
        if load > instance.vehicle_capacity + _DARP_EPS:
            out.append(DarpViolation(ReasonCode.NO_ACCESSIBLE_CAPACITY, f"onboard load {load} exceeds capacity {instance.vehicle_capacity}", route.vehicle, v.node_index))

    # Route duration: begin-service at the final depot minus at the first depot.
    if len(visits) >= 2:
        duration = visits[-1].begin_service - visits[0].begin_service
        if duration > instance.max_route_duration + _DARP_EPS:
            out.append(DarpViolation(ReasonCode.SHIFT_END, f"route duration {duration:.4f} exceeds maximum {instance.max_route_duration:.1f}", route.vehicle))

    return out


def _check_pairing(instance: DarpInstance, solution: DarpSolution, n: int) -> list[DarpViolation]:
    out: list[DarpViolation] = []
    # Map each request node to (vehicle, position, begin_service).
    location: dict[int, tuple[int, int, float]] = {}
    for route in solution.routes:
        for pos, v in enumerate(route.visits):
            if v.node_index not in (instance.depot_start, instance.depot_end):
                location[v.node_index] = (route.vehicle, pos, v.begin_service)

    for r in range(1, n + 1):
        p = instance.pickup_index(r)
        d = instance.dropoff_index(r)
        p_here, d_here = p in location, d in location
        if not p_here and not d_here:
            continue  # request left entirely unserved -- not a violation, just uncovered
        if p_here != d_here:
            missing = "drop-off" if p_here else "pickup"
            out.append(DarpViolation(ReasonCode.PRECEDENCE, f"request {r} is missing its {missing}", request=r))
            continue
        (pv, pp, pb) = location[p]
        (dv, dp, db) = location[d]
        if pv != dv:
            out.append(DarpViolation(ReasonCode.PRECEDENCE, f"request {r} pickup and drop-off are on different vehicles ({pv} vs {dv})", request=r))
            continue
        if pp >= dp:
            out.append(DarpViolation(ReasonCode.PRECEDENCE, f"request {r} drop-off is not after its pickup on vehicle {pv}", vehicle=pv, request=r))
            continue
        # Max ride time: from departure at pickup (begin + service) to begin at drop-off.
        pickup_service = instance.nodes[p].service_duration
        ride = db - (pb + pickup_service)
        if ride > instance.max_ride_time + _DARP_EPS:
            out.append(DarpViolation(ReasonCode.MAX_RIDE_TIME, f"request {r} ride time {ride:.4f} exceeds maximum {instance.max_ride_time:.1f}", vehicle=pv, request=r))
    return out


def is_darp_feasible(instance: DarpInstance, solution: DarpSolution) -> bool:
    """True iff the routed solution breaks no hard constraint. Raises
    `MalformedDarpSolution` for a structurally invalid answer."""
    return not check_darp_feasibility(instance, solution)
