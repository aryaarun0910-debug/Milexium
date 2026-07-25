"""CP-SAT backend for the v0.1 Decision IR (Program F, v0.3).

`packages.decide.solver` line 24 recorded "CP-SAT / MILP / SMT / a portfolio" as
Specified. This module builds the first of those: a real constraint-programming
model of a `DecisionProblem`, solved by OR-Tools CP-SAT, returning the same
`DecisionSolution` with the same honest status contract as the hand-rolled
branch-and-bound it sits beside.

THE DISCRETIZATION IS DELIBERATELY IDENTICAL to the exact backend's. This module
imports `_candidate_times` from `packages.decide.solver` rather than
re-deriving the grid, so both backends search *exactly the same* candidate set:
the pickup instants on the policy's time grid. That is what makes their reported
objectives directly comparable, and it is what lets the conformance suite assert
that two completely independent search procedures agree on the optimum. If this
module built its own grid, a disagreement would be ambiguous (a modelling
difference or a bug?) and the cross-check would be worthless.

Model:

- `x[r][v]` -- request r is served by vehicle v; `sum_v x[r][v] <= 1`.
- `start[r][v]` -- pickup instant, domain = the exact candidate list for (r, v).
  A pair with no candidate gets no variable and `x[r][v]` is fixed to 0.
- An optional interval [pickup, pickup + nominal_ride) per (r, v), fed to two
  `AddCumulative` constraints per vehicle (ambulatory seats, wheelchair
  positions). Cumulative treats intervals as half-open, so a drop-off frees the
  seat at the instant the next pickup takes it -- the same boundary convention
  the independent checker's sweep uses, deliberately.
- Objective: the exact objective the branch-and-bound minimises -- weighted
  in-vehicle minutes for served requests, plus `unserved_penalty` per denied
  optional request and a dominating penalty per denied mandated request.

Two scalings, both stated rather than hidden:

- TIME is modelled in integer microseconds from an origin. `datetime` resolves
  to microseconds, so this is exact for any instant the IR can hold.
- The OBJECTIVE is modelled in integer thousandths. A policy whose weights need
  finer resolution than 0.001 would be rounded; the model refuses to run rather
  than round silently past `_MAX_SCALED_OBJECTIVE`.

Honest status, same contract as the rest of Program F: CP-SAT `OPTIMAL` becomes
`OPTIMAL` (gap 0, relative to the grid) -- or `INFEASIBLE` when the proven
optimum leaves a mandated request unserved, which is a *proof* that no schedule
serves every mandate. Anything short of a proof becomes `TIMEOUT`, never
`OPTIMAL`. The dual bound CP-SAT knows at a timeout is real and is carried on
`CpSatOutcome`, NOT on `DecisionSolution` -- that type's documented contract is
that `bound`/`gap` are populated only behind a genuine optimality claim, and
this backend does not get to weaken it.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from packages.canonical.vocab import ReasonCode, ScheduleRunStatus
from packages.decide.capability import SolverUnavailable, ortools_capability
from packages.decide.feasibility import check_feasibility
from packages.decide.ir import (
    Assignment,
    DecisionProblem,
    DecisionSolution,
    Denial,
)
# Imported on purpose: both backends must discretize the problem IDENTICALLY, or
# comparing their objectives proves nothing. See the module docstring.
from packages.decide.solver import (
    _MUST_SERVE_PENALTY,
    _candidate_times,
    _static_reasons,
)

CPSAT_SOLVER_NAME = "milexium-decide-cpsat"
CPSAT_SOLVER_VERSION = "0.3.0"

_US_PER_MINUTE = 60_000_000
_OBJ_SCALE = 1000  # objective modelled in integer thousandths
_MAX_SCALED_OBJECTIVE = 2**62  # stay well inside CP-SAT's int64 coefficient range


class CpSatModelTooLarge(ValueError):
    """The scaled objective would not fit safely in CP-SAT's integer domain.

    Raised instead of silently truncating: a wrapped-around penalty would make
    the solver cheerfully "prove" that dropping a mandated rider is optimal.
    """


@dataclass(frozen=True)
class CpSatOutcome:
    """A CP-SAT run: the solution plus the dual information the IR deliberately
    does not carry on a non-optimal result.

    `bound` is CP-SAT's best objective bound -- a valid LOWER bound on the
    optimum of the modelled (grid-discretized) problem, available even when the
    search was cut short. `gap` is the relative gap between the incumbent and
    that bound, or 0.0 on a proven optimum. `hit_limit` records that a budget
    bound the search, which is what makes the status TIMEOUT rather than a proof.
    """

    solution: DecisionSolution
    raw_status: str
    objective: float | None
    bound: float | None
    gap: float | None
    wall_time_s: float
    deterministic_time: float
    hit_limit: bool


def solve_cpsat(
    problem: DecisionProblem,
    *,
    seed: int = 0,
    max_deterministic_time: float | None = 30.0,
    max_time_s: float | None = None,
    workers: int = 1,
) -> DecisionSolution:
    """Solve with CP-SAT, returning the same `DecisionSolution` shape as
    `packages.decide.solver.solve`."""
    return solve_cpsat_detailed(
        problem,
        seed=seed,
        max_deterministic_time=max_deterministic_time,
        max_time_s=max_time_s,
        workers=workers,
    ).solution


def solve_cpsat_detailed(
    problem: DecisionProblem,
    *,
    seed: int = 0,
    max_deterministic_time: float | None = 30.0,
    max_time_s: float | None = None,
    workers: int = 1,
) -> CpSatOutcome:
    """Solve with CP-SAT and report the dual bound alongside the solution.

    Determinism: with `workers=1` and a `max_deterministic_time` budget (and NO
    wall-clock cap), CP-SAT's search is reproducible -- the same problem and seed
    give the same answer on any machine, regardless of how fast it is.
    `max_time_s` is a wall-clock escape hatch; setting it makes the run
    reproducible only on hardware of comparable speed, and the portfolio records
    that honestly rather than claiming determinism it did not buy.
    """
    cap = ortools_capability()
    if not cap.available:
        raise SolverUnavailable(f"CP-SAT backend requires OR-Tools: {cap.detail}")
    from ortools.sat.python import cp_model

    policy = problem.policy
    requests = sorted(problem.requests, key=lambda r: (r.pickup_window_start, str(r.request_id)))
    vehicles = sorted(problem.vehicles, key=lambda v: str(v.vehicle_id))

    origin = _origin(problem)
    model = cp_model.CpModel()

    def us(t: datetime) -> int:
        return round((t - origin).total_seconds() * 1_000_000)

    # --- variables ---------------------------------------------------------
    x: dict[tuple[int, int], object] = {}
    starts: dict[tuple[int, int], object] = {}
    per_vehicle_intervals: dict[int, list[tuple[object, int, bool]]] = {vi: [] for vi in range(len(vehicles))}

    for ri, req in enumerate(requests):
        ride_us = round(req.nominal_ride_time_minutes * _US_PER_MINUTE)
        served_lits = []
        for vi, veh in enumerate(vehicles):
            candidates = _candidate_times(req, veh, policy.time_granularity_minutes)
            if not candidates:
                continue  # this vehicle can never take this request; no variable at all
            lit = model.NewBoolVar(f"x_r{ri}_v{vi}")
            domain = cp_model.Domain.FromValues(sorted({us(c) for c in candidates}))
            st = model.NewIntVarFromDomain(domain, f"start_r{ri}_v{vi}")
            iv = model.NewOptionalIntervalVar(st, ride_us, st + ride_us, lit, f"iv_r{ri}_v{vi}")
            x[(ri, vi)] = lit
            starts[(ri, vi)] = st
            demand = 1 if req.needs_wheelchair else req.party_size
            per_vehicle_intervals[vi].append((iv, demand, req.needs_wheelchair))
            served_lits.append(lit)
        if served_lits:
            model.AddAtMostOne(served_lits)

    # --- capacity ----------------------------------------------------------
    for vi, veh in enumerate(vehicles):
        for wheelchair, capacity in ((True, veh.capacity_wheelchair), (False, veh.capacity_ambulatory)):
            ivs = [(iv, dem) for iv, dem, is_wc in per_vehicle_intervals[vi] if is_wc is wheelchair]
            if not ivs:
                continue
            model.AddCumulative([iv for iv, _ in ivs], [dem for _, dem in ivs], capacity)

    # --- objective ---------------------------------------------------------
    # Identical to the branch-and-bound's: serving costs weighted in-vehicle
    # minutes; denying costs the penalty. Expressed as a constant (deny
    # everything) plus the saving from each service decision, which keeps the
    # coefficients small and the two objectives numerically equal.
    constant = 0
    terms = []
    for ri, req in enumerate(requests):
        penalty = _MUST_SERVE_PENALTY if req.must_serve else policy.unserved_penalty
        serve_cost = policy.ride_time_weight * req.nominal_ride_time_minutes
        scaled_penalty = round(penalty * _OBJ_SCALE)
        scaled_serve = round(serve_cost * _OBJ_SCALE)
        constant += scaled_penalty
        delta = scaled_serve - scaled_penalty  # negative when serving is worth it
        for vi in range(len(vehicles)):
            lit = x.get((ri, vi))
            if lit is not None:
                terms.append(delta * lit)
    if constant >= _MAX_SCALED_OBJECTIVE:
        raise CpSatModelTooLarge(
            f"scaled objective bound {constant} exceeds the safe integer range "
            f"({_MAX_SCALED_OBJECTIVE}); reduce the request count or the mandated penalty"
        )
    model.Minimize(sum(terms) + constant)

    # --- solve -------------------------------------------------------------
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = workers
    solver.parameters.random_seed = seed
    if max_deterministic_time is not None:
        solver.parameters.max_deterministic_time = max_deterministic_time
    if max_time_s is not None:
        solver.parameters.max_time_in_seconds = max_time_s
    t0 = time.perf_counter()
    status = solver.Solve(model)
    wall = time.perf_counter() - t0
    status_name = solver.StatusName(status)

    has_solution = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    proven = status == cp_model.OPTIMAL

    assign: list[tuple[int, int, datetime, datetime]] = []
    if has_solution:
        for (ri, vi), lit in x.items():
            if solver.BooleanValue(lit):
                req = requests[ri]
                pickup = origin + timedelta(microseconds=int(solver.Value(starts[(ri, vi)])))
                assign.append((ri, vi, pickup, pickup + req.nominal_ride))

    # The modelled objective is integral by construction, but CP-SAT reports it
    # as a double. Round back onto the integer lattice before unscaling, or the
    # comparison with the branch-and-bound's exact float arithmetic fails on
    # noise of ~1e-5 and a cross-check that should be exact becomes approximate.
    objective = round(solver.ObjectiveValue()) / _OBJ_SCALE if has_solution else None
    # The bound is FLOORED, never rounded: on a minimisation it must stay a valid
    # lower bound, and rounding up could overstate it past the true optimum.
    raw_bound = (
        math.floor(solver.BestObjectiveBound()) / _OBJ_SCALE
        if status != cp_model.INFEASIBLE
        else None
    )
    if proven and objective is not None:
        raw_bound = objective  # a proof: bound and incumbent coincide exactly
    gap = _relative_gap(objective, raw_bound, proven)

    solution = _build_solution(problem, requests, vehicles, assign, objective, proven, has_solution, seed)
    # One-way self-audit against the INDEPENDENT checker, exactly as the
    # hand-rolled backend does. A CP-SAT model bug must fail loudly here, not
    # ship as a "solution" carrying an optimality certificate.
    violations = check_feasibility(problem, solution)
    if violations:
        raise AssertionError(f"CP-SAT produced an infeasible solution: {violations}")

    return CpSatOutcome(
        solution=solution,
        raw_status=status_name,
        objective=objective,
        bound=raw_bound,
        gap=gap,
        wall_time_s=round(wall, 4),
        deterministic_time=round(solver.deterministic_time, 4),
        hit_limit=not proven,
    )


# --- helpers --------------------------------------------------------------

def _origin(problem: DecisionProblem) -> datetime:
    """A fixed epoch for the integer time model: the earliest instant anything in
    the problem refers to, so every modelled time is non-negative."""
    candidates = [v.shift_start for v in problem.vehicles]
    candidates += [r.pickup_window_start for r in problem.requests]
    return min(candidates)


def _relative_gap(objective: float | None, bound: float | None, proven: bool) -> float | None:
    if proven:
        return 0.0
    if objective is None or bound is None:
        return None
    if objective == 0.0:
        return 0.0 if bound == 0.0 else None
    return abs(objective - bound) / abs(objective)


def _build_solution(problem, requests, vehicles, assign, objective, proven, has_solution, seed) -> DecisionSolution:
    served_idx = {ri for ri, _v, _p, _d in assign}
    served_ids = {str(requests[ri].request_id) for ri in served_idx}

    if proven:
        mandated_missing = [r for r in requests if r.must_serve and str(r.request_id) not in served_ids]
        if mandated_missing:
            # A PROOF, not a shrug: the optimum of a model that is free to deny
            # any request still leaves a mandate unserved, so no schedule serves
            # every mandate. Same verdict the branch-and-bound reaches.
            unserved = tuple(
                Denial(request_id=r.request_id, reason_codes=_static_reasons(r, problem))
                for r in problem.requests
            )
            return _mk(ScheduleRunStatus.INFEASIBLE, (), unserved, None, None, None, seed)

        assignments = tuple(
            Assignment(
                request_id=requests[ri].request_id,
                vehicle_id=vehicles[vi].vehicle_id,
                pickup_time=pt,
                dropoff_time=dt,
            )
            for ri, vi, pt, dt in sorted(assign, key=lambda a: (str(requests[a[0]].request_id)))
        )
        unserved = tuple(
            Denial(request_id=r.request_id, reason_codes=_static_reasons(r, problem))
            for r in problem.requests
            if str(r.request_id) not in served_ids
        )
        return _mk(ScheduleRunStatus.OPTIMAL, assignments, unserved, objective, objective, 0.0, seed)

    # Not proven: an incumbent (or nothing). TIMEOUT, never OPTIMAL, and no
    # bound/gap on the DecisionSolution -- they live on CpSatOutcome instead.
    assignments = tuple(
        Assignment(
            request_id=requests[ri].request_id,
            vehicle_id=vehicles[vi].vehicle_id,
            pickup_time=pt,
            dropoff_time=dt,
        )
        for ri, vi, pt, dt in sorted(assign, key=lambda a: (str(requests[a[0]].request_id)))
    )
    unserved = tuple(
        Denial(request_id=r.request_id, reason_codes=(ReasonCode.SOLVER_TIMEOUT,))
        for r in problem.requests
        if str(r.request_id) not in served_ids
    )
    return _mk(
        ScheduleRunStatus.TIMEOUT,
        assignments,
        unserved,
        objective if has_solution else None,
        None,
        None,
        seed,
    )


def _mk(status, assignments, unserved, objective, bound, gap, seed) -> DecisionSolution:
    return DecisionSolution(
        status=status,
        assignments=assignments,
        unserved=unserved,
        objective_value=objective,
        bound=bound,
        gap=gap,
        seed=seed,
        solver_name=CPSAT_SOLVER_NAME,
        solver_version=CPSAT_SOLVER_VERSION,
    )
