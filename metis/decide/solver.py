"""Decision solver (Program F candidate generator, v0.1).

Produces a `DecisionSolution` for a `DecisionProblem`. This is the *candidate
generator*; it is deliberately a separate module from the independent
feasibility checker (`metis.decide.feasibility`), and the dependency only
runs one way -- this module imports the checker to self-audit its own output
before returning, but the checker never imports this module. A generator that
graded its own homework would not be a check; the separation is the point.

Two backends, one honest status contract:

- Exact branch-and-bound over pickup times on the policy's time grid, for small
  instances (<= `policy.exact_max_requests`). When it exhausts the search within
  the node budget it returns OPTIMAL with gap 0 (optimal relative to the grid),
  or INFEASIBLE when it proves a must_serve request cannot be scheduled. If the
  node budget is exhausted first it returns TIMEOUT with whatever incumbent it
  has -- NEVER OPTIMAL. Reporting a timeout incumbent as a proven optimum is the
  named failure mode in blueprint 15; this backend cannot do it.
- Greedy cheapest-first insertion for larger instances, returning FEASIBLE with
  no bound/gap -- "a feasible plan, not proven optimal." Greedy never emits
  INFEASIBLE: not serving a request does not prove none exists.

Determinism: fully deterministic; `seed` only breaks ties in the greedy backend
and is recorded on the solution for reproducibility. CP-SAT / MILP / SMT / a
heuristic portfolio are Specified (blueprint 06), not built here.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from themis.canonical.vocab import ReasonCode, ScheduleRunStatus
from metis.decide.feasibility import check_feasibility
from metis.decide.ir import (
    Assignment,
    Denial,
    DecisionProblem,
    DecisionSolution,
    DecisionVehicle,
    RideRequest,
)

SOLVER_NAME = "milexium-decide"
SOLVER_VERSION = "0.1.0"

_MUST_SERVE_PENALTY = 1e12  # Dominates the objective so the optimum serves every mandated trip if it possibly can.


def solve(problem: DecisionProblem, *, seed: int = 0) -> DecisionSolution:
    """Solve a decision problem, reporting an honest solver status."""
    if len(problem.requests) <= problem.policy.exact_max_requests:
        solution = _solve_exact(problem, seed)
    else:
        solution = _solve_greedy(problem, seed)
    _self_audit(problem, solution)
    return solution


# --- candidate generation -------------------------------------------------

def _candidate_times(req: RideRequest, veh: DecisionVehicle, granularity: int) -> list[datetime]:
    """Feasible pickup instants for `req` on `veh` on the time grid. Empty if the
    request cannot ride this vehicle at all (wrong capacity type, or no grid
    point satisfies windows/shift/ride-time)."""
    if req.needs_wheelchair and veh.capacity_wheelchair < 1:
        return []
    if not req.needs_wheelchair and veh.capacity_ambulatory < req.party_size:
        return []
    if req.nominal_ride_time_minutes > req.max_ride_time_minutes:
        return []
    dur = req.nominal_ride
    earliest = max(req.pickup_window_start, veh.shift_start)
    if req.dropoff_window_start is not None:
        earliest = max(earliest, req.dropoff_window_start - dur)
    latest = min(req.pickup_window_end, req.dropoff_window_end - dur, veh.shift_end - dur)
    if earliest > latest:
        return []
    step = timedelta(minutes=granularity)
    out: list[datetime] = []
    t = earliest
    while t <= latest:
        out.append(t)
        t += step
    return out


def _static_reasons(req: RideRequest, problem: DecisionProblem) -> tuple[ReasonCode, ...]:
    """Best-effort reason codes for a request no vehicle can ever ride (checked
    in isolation, before capacity contention). The binding hard constraints."""
    if req.nominal_ride_time_minutes > req.max_ride_time_minutes:
        return (ReasonCode.MAX_RIDE_TIME,)
    reasons: set[ReasonCode] = set()
    dur = req.nominal_ride
    for veh in problem.vehicles:
        if req.needs_wheelchair and veh.capacity_wheelchair < 1:
            reasons.add(ReasonCode.NO_ACCESSIBLE_CAPACITY)
            continue
        if not req.needs_wheelchair and veh.capacity_ambulatory < req.party_size:
            reasons.add(ReasonCode.NO_ACCESSIBLE_CAPACITY)
            continue
        earliest = max(req.pickup_window_start, veh.shift_start)
        latest = min(req.pickup_window_end, req.dropoff_window_end - dur, veh.shift_end - dur)
        if earliest > latest:
            if earliest > req.pickup_window_end:
                reasons.add(ReasonCode.PICKUP_WINDOW)
            if req.dropoff_window_end - dur < earliest:
                reasons.add(ReasonCode.DROPOFF_WINDOW)
            if veh.shift_end - dur < earliest or req.pickup_window_start < veh.shift_start:
                reasons.add(ReasonCode.SHIFT_END)
    return tuple(sorted(reasons, key=lambda r: r.value)) or (ReasonCode.NO_ACCESSIBLE_CAPACITY,)


def _fits_capacity(placed: list[tuple], veh: DecisionVehicle, req: RideRequest, pickup: datetime, dropoff: datetime) -> bool:
    """Would adding [pickup, dropoff] keep `veh` within capacity for req's type?
    `placed` is (pickup, dropoff, is_wheelchair, load) already on this vehicle."""
    is_wc = req.needs_wheelchair
    capacity = veh.capacity_wheelchair if is_wc else veh.capacity_ambulatory
    load = 1 if is_wc else req.party_size
    # Peak concurrent load of this type over the new interval, sweeping boundaries.
    events = [(pickup, load), (dropoff, -load)]
    for p, d, other_wc, other_load in placed:
        if other_wc != is_wc:
            continue
        events.append((p, other_load))
        events.append((d, -other_load))
    events.sort(key=lambda e: (e[0], e[1]))  # dropoff (-) before pickup (+) at equal instants
    onboard = 0
    for _t, delta in events:
        onboard += delta
        if onboard > capacity:
            return False
    return True


# --- exact backend --------------------------------------------------------

def _solve_exact(problem: DecisionProblem, seed: int) -> DecisionSolution:
    policy = problem.policy
    requests = sorted(problem.requests, key=lambda r: (r.pickup_window_start, str(r.request_id)))
    vehicles = {str(v.vehicle_id): v for v in problem.vehicles}

    options: dict[str, list[tuple]] = {}
    for req in requests:
        opts: list[tuple] = []
        for veh in problem.vehicles:
            for pt in _candidate_times(req, veh, policy.time_granularity_minutes):
                opts.append((str(veh.vehicle_id), pt, pt + req.nominal_ride))
        options[str(req.request_id)] = opts

    best_cost = [float("inf")]
    best_assign: list[list[tuple] | None] = [None]
    nodes = [0]
    timed_out = [False]
    # per-vehicle list of placed (pickup, dropoff, is_wheelchair, load)
    placed: dict[str, list[tuple]] = {vid: [] for vid in vehicles}
    chosen: list[tuple] = []

    def penalty(req: RideRequest) -> float:
        return _MUST_SERVE_PENALTY if req.must_serve else policy.unserved_penalty

    def dfs(i: int, cost: float) -> None:
        nodes[0] += 1
        if nodes[0] > policy.max_search_nodes:
            timed_out[0] = True
            return
        if cost >= best_cost[0]:  # committed cost only grows -> admissible prune
            return
        if i == len(requests):
            best_cost[0] = cost
            best_assign[0] = list(chosen)
            return
        req = requests[i]
        rid = str(req.request_id)
        for vid, pt, dt in options[rid]:
            veh = vehicles[vid]
            if _fits_capacity(placed[vid], veh, req, pt, dt):
                placed[vid].append((pt, dt, req.needs_wheelchair, 1 if req.needs_wheelchair else req.party_size))
                chosen.append((rid, vid, pt, dt))
                dfs(i + 1, cost + policy.ride_time_weight * req.nominal_ride_time_minutes)
                chosen.pop()
                placed[vid].pop()
                if timed_out[0]:
                    return
        # Or leave it unserved.
        dfs(i + 1, cost + penalty(req))
        return

    dfs(0, 0.0)

    if timed_out[0]:
        return _timeout_solution(problem, best_assign[0], best_cost[0], seed)
    return _completed_solution(problem, best_assign[0], best_cost[0], seed)


def _completed_solution(problem: DecisionProblem, assign: list[tuple] | None, cost: float, seed: int) -> DecisionSolution:
    served = {rid for rid, _v, _p, _d in (assign or [])}
    must_serve_unserved = [r for r in problem.requests if r.must_serve and str(r.request_id) not in served]

    if must_serve_unserved:
        # Proven: no schedule serves every mandated request. No plan is accepted.
        unserved = tuple(
            Denial(request_id=r.request_id, reason_codes=_static_reasons(r, problem))
            for r in problem.requests
        )
        return _mk_solution(ScheduleRunStatus.INFEASIBLE, (), unserved, None, None, None, seed)

    assignments = tuple(
        Assignment(request_id=_rid(problem, rid), vehicle_id=_vid(problem, vid), pickup_time=pt, dropoff_time=dt)
        for rid, vid, pt, dt in (assign or [])
    )
    unserved = tuple(
        Denial(request_id=r.request_id, reason_codes=_static_reasons(r, problem))
        for r in problem.requests
        if str(r.request_id) not in served
    )
    return _mk_solution(ScheduleRunStatus.OPTIMAL, assignments, unserved, cost, cost, 0.0, seed)


def _timeout_solution(problem: DecisionProblem, assign: list[tuple] | None, cost: float, seed: int) -> DecisionSolution:
    served = {rid for rid, _v, _p, _d in (assign or [])}
    assignments = tuple(
        Assignment(request_id=_rid(problem, rid), vehicle_id=_vid(problem, vid), pickup_time=pt, dropoff_time=dt)
        for rid, vid, pt, dt in (assign or [])
    )
    # Anything unresolved when the budget ran out is denied SOLVER_TIMEOUT unless
    # it was statically impossible anyway -- we do not claim to know which.
    unserved = tuple(
        Denial(request_id=r.request_id, reason_codes=(ReasonCode.SOLVER_TIMEOUT,))
        for r in problem.requests
        if str(r.request_id) not in served
    )
    objective = cost if assign is not None else None
    # TIMEOUT: no bound, no gap. An incumbent is not a proven optimum.
    return _mk_solution(ScheduleRunStatus.TIMEOUT, assignments, unserved, objective, None, None, seed)


# --- greedy backend -------------------------------------------------------

def _solve_greedy(problem: DecisionProblem, seed: int) -> DecisionSolution:
    policy = problem.policy
    # Deterministic order; seed perturbs ties only. A stable (non-salted) hash so
    # a given seed reproduces the same plan across processes, not just within one.
    def _tiebreak(rid: str) -> str:
        return hashlib.sha256(f"{seed}:{rid}".encode()).hexdigest()

    requests = sorted(problem.requests, key=lambda r: (r.pickup_window_start, _tiebreak(str(r.request_id)), str(r.request_id)))
    vehicles = {str(v.vehicle_id): v for v in problem.vehicles}
    placed: dict[str, list[tuple]] = {vid: [] for vid in vehicles}

    assignments: list[Assignment] = []
    denials: list[Denial] = []
    total_cost = 0.0
    for req in requests:
        chosen = None
        for veh in problem.vehicles:
            for pt in _candidate_times(req, veh, policy.time_granularity_minutes):
                dt = pt + req.nominal_ride
                if _fits_capacity(placed[str(veh.vehicle_id)], veh, req, pt, dt):
                    chosen = (str(veh.vehicle_id), pt, dt)
                    break
            if chosen is not None:
                break
        if chosen is None:
            denials.append(Denial(request_id=req.request_id, reason_codes=_static_reasons(req, problem)))
            total_cost += _MUST_SERVE_PENALTY if req.must_serve else policy.unserved_penalty
            continue
        vid, pt, dt = chosen
        placed[vid].append((pt, dt, req.needs_wheelchair, 1 if req.needs_wheelchair else req.party_size))
        assignments.append(Assignment(request_id=req.request_id, vehicle_id=_vid(problem, vid), pickup_time=pt, dropoff_time=dt))
        total_cost += policy.ride_time_weight * req.nominal_ride_time_minutes

    # FEASIBLE, never OPTIMAL/INFEASIBLE: greedy neither proves optimality nor
    # proves that an unserved request was impossible.
    return _mk_solution(ScheduleRunStatus.FEASIBLE, tuple(assignments), tuple(denials), total_cost, None, None, seed)


# --- helpers --------------------------------------------------------------

def _rid(problem: DecisionProblem, rid: str):
    return next(r.request_id for r in problem.requests if str(r.request_id) == rid)


def _vid(problem: DecisionProblem, vid: str):
    return next(v.vehicle_id for v in problem.vehicles if str(v.vehicle_id) == vid)


def _mk_solution(status, assignments, unserved, objective, bound, gap, seed) -> DecisionSolution:
    return DecisionSolution(
        status=status,
        assignments=assignments,
        unserved=unserved,
        objective_value=objective,
        bound=bound,
        gap=gap,
        seed=seed,
        solver_name=SOLVER_NAME,
        solver_version=SOLVER_VERSION,
    )


def _self_audit(problem: DecisionProblem, solution: DecisionSolution) -> None:
    """The generator's own accepted assignments must pass the INDEPENDENT
    checker before we return them. If they don't, that's a solver bug and we
    fail loudly rather than emit an infeasible 'solution'. This is the one-way
    dependency (solver -> checker) that keeps the two honest."""
    violations = check_feasibility(problem, solution)
    if violations:
        raise AssertionError(f"solver produced an infeasible solution: {violations}")
