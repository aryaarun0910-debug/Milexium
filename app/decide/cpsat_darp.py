"""CP-SAT model for the routed dial-a-ride problem (Program F, v0.3).

`app.decide.darp_solver` is a heuristic: it finds good routes and proves
nothing. This module is its complement -- an exact constraint model of the same
`DarpInstance`, solved by OR-Tools CP-SAT, whose value to the portfolio is
primarily the DUAL BOUND. On the published Cordeau instances the heuristic
almost always wins on primal quality; CP-SAT is what turns "our answer is 317.7"
into "our answer is 317.7 and no answer below B exists", which is the only way to
state a gap without borrowing someone else's published optimum.

WHY THE BOUND IS VALID (the load-bearing argument -- if this is wrong, every
number this module reports is wrong).

CP-SAT is an integer solver and the instances are Euclidean, so distances and
travel times are irrational. The model therefore works on a scaled integer
lattice (`_SCALE` units per minute / per distance unit) and every rounding
direction is chosen so the modelled problem is a RELAXATION of the true one:

- travel times and objective coefficients are FLOORED   (cheaper, weaker);
- time-window / ride-time / duration UPPER bounds are CEILED and given a further
  `_RELAX` units of slack (looser);
- time-window LOWER bounds are FLOORED (looser).

Under those directions, the exact-optimal routing R* -- scheduled at its true
times and mapped onto the lattice by flooring -- satisfies every modelled
constraint (the flooring slack on each of the two terms being subtracted is what
`_RELAX` absorbs), and its modelled objective is at most `_SCALE` times its true
distance. Hence

    modelled_optimum <= _SCALE * true_optimum

and since CP-SAT's `BestObjectiveBound()` is a lower bound on the modelled
optimum, `floor(BestObjectiveBound()) / _SCALE` is a rigorous lower bound on the
TRUE optimum -- available even when the search is cut off long before proving
anything. That is the number this module reports, and it is the only claim it
makes.

The converse does NOT hold and is handled explicitly: because the model is a
relaxation, a routing CP-SAT calls feasible may be infeasible for the true
instance. So a sequence CP-SAT produces is never reported as a solution on
CP-SAT's say-so. It is re-scheduled in exact float arithmetic and then judged by
the INDEPENDENT checker (`app.decide.feasibility.check_darp_feasibility`).
If the checker objects, the outcome records `sequence_rejected` and carries the
bound alone. A relaxation's route is a suggestion; only the checker's verdict
counts.

That re-scheduling needed a new exact routine (`exact_schedule` below). The
existing `darp_solver.schedule_route` is Cordeau & Laporte's eight-step
evaluation: sound but INCOMPLETE, and it was rejecting model-optimal routings
that do have feasible schedules. Scheduling a fixed sequence is a difference-
constraint system, so it can be solved exactly; `exact_schedule` does that and
`schedule_route` is kept as a fallback second opinion, unmodified.

Formulation: one `AddMultipleCircuit` over nodes {depot} U {1..2n}, self-loops
omitted so every request node must be visited. Route identity is carried by a
`route[i]` label equal to the index of the route's first node -- distinct routes
have distinct first nodes, so equal labels genuinely mean same vehicle, which is
what pairs a pickup with its drop-off. Depot departure `RD[i]` propagates along
each route so the max-route-duration constraint is measured from the vehicle's
actual departure rather than from time zero (fixing departure at zero would be a
RESTRICTION and would silently invalidate the bound).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from app.decide.capability import SolverUnavailable, ortools_capability
from app.decide.darp_ir import DarpInstance, DarpRoute, DarpSolution, DarpVisit
from app.decide.darp_solver import route_distance, schedule_route
from app.decide.feasibility import check_darp_feasibility

CPSAT_DARP_SOLVER_NAME = "milexium-decide-darp-cpsat"
CPSAT_DARP_SOLVER_VERSION = "0.3.0"

_SCALE = 1_000_000  # lattice units per minute / per distance unit
_RELAX = 4          # extra lattice units on every upper bound; guarantees relaxation


class DarpModelUnsupported(ValueError):
    """The instance violates an assumption the model depends on.

    Currently: the two depot nodes must be co-located, since the circuit model
    merges them into one node. Raised rather than silently modelling a different
    problem than the one on disk.
    """


@dataclass(frozen=True)
class CpSatDarpOutcome:
    """A CP-SAT run on a DARP instance.

    `lower_bound` is a rigorous lower bound on the TRUE (unrounded, Euclidean)
    optimum -- see the module docstring for why. `solution` is present only when
    CP-SAT produced a routing that the exact scheduler AND the independent
    checker both accepted; `sequence_rejected` records the case where it produced
    one they did not, which is a real possibility for a relaxation and is
    reported rather than papered over.

    `proved_model_optimal` says CP-SAT closed the *modelled* problem. It does NOT
    mean the reported route is the true optimum, because the model is a
    relaxation -- if `solution` also survived exact verification and its distance
    equals the bound, then and only then is optimality of the true instance
    established, which `certified_optimal` computes.
    """

    instance_name: str
    solution: DarpSolution | None
    lower_bound: float | None
    raw_status: str
    proved_model_optimal: bool
    sequence_rejected: bool
    wall_time_s: float
    deterministic_time: float
    detail: str
    scale: int = _SCALE
    relax: int = _RELAX
    # The most the lattice bound can understate the true optimum: every arc in a
    # complete routing loses at most one lattice unit to flooring, and a routing
    # uses at most 2n + K arcs. Computed by the solver, not guessed.
    lattice_tolerance: float = 0.0

    @property
    def objective(self) -> float | None:
        return self.solution.objective if self.solution is not None else None

    @property
    def certified_optimal(self) -> bool:
        """True only when an exactly-verified route's true distance meets the
        rigorous lower bound, WITHIN THE LATTICE RESOLUTION. That qualifier is
        the whole claim: like the grid-exact backend's "optimal relative to the
        time grid", this certifies optimality up to a stated, computed error --
        never absolutely. A caller quoting this must quote the tolerance with it."""
        obj = self.objective
        if obj is None or self.lower_bound is None:
            return False
        return obj <= self.lower_bound + self.lattice_tolerance


def solve_darp_cpsat(
    instance: DarpInstance,
    *,
    seed: int = 0,
    max_deterministic_time: float | None = 60.0,
    max_time_s: float | None = None,
    workers: int = 1,
    scale: int = _SCALE,
    relax: int = _RELAX,
) -> CpSatDarpOutcome:
    """Build and solve the CP-SAT model for `instance`.

    Determinism: `workers=1` plus a deterministic-time budget and NO wall-clock
    cap makes the run reproducible across machines. `max_time_s` is a safety
    valve; when it is set the result is only reproducible on comparable hardware,
    and the portfolio marks the run non-deterministic.

    `scale`/`relax` define the integer lattice. They are parameters, not hidden
    constants, because the lattice is part of the claim: a coarser lattice is a
    looser relaxation, so it yields a weaker (but still valid) bound and a route
    less likely to survive exact verification. Both are recorded on the outcome.
    """
    cap = ortools_capability()
    if not cap.available:
        raise SolverUnavailable(f"CP-SAT DARP backend requires OR-Tools: {cap.detail}")
    from ortools.sat.python import cp_model

    n = instance.num_requests
    K = instance.num_vehicles
    depot_s, depot_e = instance.depot_start, instance.depot_end
    ds, de = instance.nodes[depot_s], instance.nodes[depot_e]
    if (ds.x, ds.y) != (de.x, de.y):
        raise DarpModelUnsupported(
            f"{instance.name}: start depot {(ds.x, ds.y)} and end depot {(de.x, de.y)} are not "
            "co-located; the merged-depot circuit model does not represent this instance"
        )

    nodes = list(range(0, 2 * n + 1))  # 0 = the (merged) depot, 1..2n request nodes

    def true_dist(i: int, j: int) -> float:
        """Distance in the ORIGINAL indexing, mapping the merged depot 0 onto
        whichever depot node the direction implies (they are co-located, checked
        above, so either is correct -- this keeps the intent readable)."""
        a = depot_s if i == 0 else i
        b = depot_e if j == 0 else j
        return instance.dist(a, b)

    def t_scaled(i: int, j: int) -> int:
        return math.floor(true_dist(i, j) * scale)  # FLOORED: weaker + cheaper

    def lo(v: float) -> int:
        return math.floor(v * scale)

    def hi(v: float) -> int:
        return math.ceil(v * scale) + relax

    model = cp_model.CpModel()

    depot_open = lo(ds.tw_start)
    depot_close = hi(de.tw_end)
    max_duration = hi(instance.max_route_duration)
    max_ride = hi(instance.max_ride_time)

    # --- variables ---------------------------------------------------------
    B: dict[int, object] = {}   # begin-service time (lattice units)
    RD: dict[int, object] = {}  # depot departure time of this node's route
    route: dict[int, object] = {}  # route label = index of the route's first node
    load: dict[int, object] = {}   # onboard load AFTER servicing this node
    for i in nodes[1:]:
        nd = instance.nodes[i]
        B[i] = model.NewIntVar(lo(nd.tw_start), hi(nd.tw_end), f"B{i}")
        RD[i] = model.NewIntVar(depot_open, depot_close, f"RD{i}")
        route[i] = model.NewIntVar(1, 2 * n, f"route{i}")
        load[i] = model.NewIntVar(0, instance.vehicle_capacity, f"q{i}")

    arcs: list[tuple[int, int, object]] = []
    lit: dict[tuple[int, int], object] = {}
    for i in nodes:
        for j in nodes:
            if i == j:
                continue
            # A route may not START at a drop-off, nor END right after a pickup:
            # either would strand the paired node off the route. Sound cuts --
            # both are provably infeasible once pairing and precedence hold.
            if i == 0 and j > n:
                continue
            if j == 0 and 1 <= i <= n:
                continue
            v = model.NewBoolVar(f"a_{i}_{j}")
            lit[(i, j)] = v
            arcs.append((i, j, v))
    model.AddMultipleCircuit(arcs)

    # --- vehicle count -----------------------------------------------------
    out_of_depot = [lit[(0, j)] for j in nodes[1:] if (0, j) in lit]
    model.Add(sum(out_of_depot) <= K)
    model.Add(sum(out_of_depot) >= 1)

    # --- arc-driven propagation -------------------------------------------
    for (i, j), v in lit.items():
        svc_i = 0 if i == 0 else lo(instance.nodes[i].service_duration)
        if i == 0:
            # Leaving the depot: j is this route's first node, so it labels it.
            model.Add(B[j] >= RD[j] + t_scaled(0, j)).OnlyEnforceIf(v)
            model.Add(route[j] == j).OnlyEnforceIf(v)
            model.Add(load[j] == instance.nodes[j].load).OnlyEnforceIf(v)
        elif j == 0:
            # Returning to the depot: window and max-route-duration, measured
            # from this route's ACTUAL departure.
            model.Add(B[i] + svc_i + t_scaled(i, 0) <= depot_close).OnlyEnforceIf(v)
            model.Add(B[i] + svc_i + t_scaled(i, 0) - RD[i] <= max_duration).OnlyEnforceIf(v)
        else:
            model.Add(B[j] >= B[i] + svc_i + t_scaled(i, j)).OnlyEnforceIf(v)
            model.Add(route[j] == route[i]).OnlyEnforceIf(v)
            model.Add(RD[j] == RD[i]).OnlyEnforceIf(v)
            model.Add(load[j] == load[i] + instance.nodes[j].load).OnlyEnforceIf(v)

    # --- pairing, precedence, ride time ------------------------------------
    for r in range(1, n + 1):
        p, d = instance.pickup_index(r), instance.dropoff_index(r)
        svc_p = lo(instance.nodes[p].service_duration)
        model.Add(route[p] == route[d])                       # same vehicle
        model.Add(B[d] >= B[p] + svc_p + t_scaled(p, d))      # precedence + direct travel
        model.Add(B[d] - B[p] - svc_p <= max_ride)            # ADA-style ride ceiling
        # Redundant but strong: a pickup cannot begin so late that its drop-off
        # window becomes unreachable even by the direct arc.
        model.Add(B[p] <= hi(instance.nodes[d].tw_end) - svc_p - t_scaled(p, d))

    # --- objective ---------------------------------------------------------
    model.Minimize(sum(t_scaled(i, j) * v for (i, j), v in lit.items()))

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
    status_name = solver.status_name(status)

    proved = status == cp_model.OPTIMAL
    has_solution = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    # Every arc in a complete routing loses at most one lattice unit to flooring,
    # and a routing uses at most 2n + K arcs. That product is the most the bound
    # can understate the true optimum -- a computed figure, not a fudge factor.
    lattice_tol = (2 * n + K) / scale
    bound = (
        math.floor(solver.BestObjectiveBound()) / scale
        if status != cp_model.INFEASIBLE
        else None
    )

    if not has_solution:
        return CpSatDarpOutcome(
            instance_name=instance.name,
            solution=None,
            lower_bound=bound,
            raw_status=status_name,
            proved_model_optimal=proved,
            sequence_rejected=False,
            wall_time_s=round(wall, 3),
            deterministic_time=round(solver.deterministic_time, 3),
            detail=f"CP-SAT returned {status_name} with no incumbent; bound only",
            scale=scale,
            relax=relax,
            lattice_tolerance=lattice_tol,
        )

    sequences = _extract_routes(solver, lit, nodes, n, depot_s, depot_e)
    # CP-SAT's own begin-service times, unscaled, per node. Used as LOWER BOUNDS
    # for the exact re-schedule below -- the lattice solution encodes *which*
    # stops the vehicle deliberately waits at, information the as-early
    # heuristic cannot recover on its own.
    hints = {i: solver.Value(B[i]) / scale for i in B}
    depot_departures = {seq[1]: solver.Value(RD[seq[1]]) / scale for seq in sequences if len(seq) > 2}
    solution, rejected, detail = _verify_and_build(
        instance, sequences, seed, bound, proved, hints, depot_departures
    )
    return CpSatDarpOutcome(
        instance_name=instance.name,
        solution=solution,
        lower_bound=bound,
        raw_status=status_name,
        proved_model_optimal=proved,
        sequence_rejected=rejected,
        wall_time_s=round(wall, 3),
        deterministic_time=round(solver.deterministic_time, 3),
        detail=detail,
        scale=scale,
        relax=relax,
        lattice_tolerance=lattice_tol,
    )


# --- extraction and exact verification ------------------------------------

def _extract_routes(solver, lit, nodes, n, depot_s, depot_e) -> list[list[int]]:
    """Walk the chosen arcs into node sequences in the ORIGINAL indexing, with
    the merged depot expanded back into its start/end nodes."""
    succ: dict[int, list[int]] = {}
    for (i, j), v in lit.items():
        if solver.BooleanValue(v):
            succ.setdefault(i, []).append(j)
    sequences: list[list[int]] = []
    for first in sorted(succ.get(0, [])):
        seq = [depot_s, first]
        cur = first
        guard = 0
        while cur != 0 and guard <= 2 * n + 2:
            nxt = succ.get(cur, [0])[0]
            if nxt == 0:
                break
            seq.append(nxt)
            cur = nxt
            guard += 1
        seq.append(depot_e)
        sequences.append(seq)
    return sequences


def exact_schedule(instance: DarpInstance, seq: list[int], *, max_passes: int | None = None) -> list[float] | None:
    """Exactly-minimal begin-service times for the node sequence `seq`, or None if
    the sequence admits no feasible schedule.

    Why this exists alongside `darp_solver.schedule_route`: that function is
    Cordeau & Laporte's eight-step forward-slack evaluation, which is SOUND but
    not COMPLETE -- it rejects some sequences that do have a feasible schedule,
    and it was rejecting exactly the model-optimal routings CP-SAT was handing
    over. It is not replaced (the heuristic depends on its speed inside its inner
    loop); this is a second opinion used where completeness matters more.

    The observation that makes it exact: every scheduling constraint on a FIXED
    sequence is a difference constraint --

        travel:    B[i]   - B[i-1] >= d[i-1] + t[i-1,i]
        windows:   e[i]  <= B[i]   <= l[i]
        ride time: B[q]   - B[p]   <= L + d[p]      (p pickup, q its drop-off)
        duration:  B[m-1] - B[0]   <= T

    -- so the system is a shortest-path feasibility problem. Raising every B to
    the least fixpoint of the lower-bound constraints yields the componentwise
    MINIMAL solution; a difference system is feasible iff that minimum respects
    every upper bound. So a None here means genuinely infeasible, not merely
    "the heuristic gave up", up to the pass budget (non-convergence also returns
    None, honestly indistinguishable from infeasible to the caller).

    Sound regardless: the caller verifies whatever this returns with the
    INDEPENDENT checker before trusting it.
    """
    nodes = instance.nodes
    m = len(seq)
    if m < 2:
        return None
    n = instance.num_requests

    e = [nodes[s].tw_start for s in seq]
    l = [nodes[s].tw_end for s in seq]
    svc = [nodes[s].service_duration for s in seq]
    travel = [0.0] + [instance.dist(seq[i - 1], seq[i]) for i in range(1, m)]

    load = 0
    for s in seq:
        load += nodes[s].load
        if load < 0 or load > instance.vehicle_capacity:
            return None  # capacity is order-only; no schedule can repair it

    pickup_pos: dict[int, int] = {}
    dropoff_pos: dict[int, int] = {}
    for idx, s in enumerate(seq):
        if 1 <= s <= n:
            pickup_pos[s] = idx
        elif n + 1 <= s <= 2 * n:
            dropoff_pos[s - n] = idx
    if set(pickup_pos) != set(dropoff_pos):
        return None
    pairs = [(pickup_pos[r], dropoff_pos[r]) for r in sorted(pickup_pos)]
    for p, q in pairs:
        if p >= q:
            return None  # drop-off before its pickup: an ordering fault, not a timing one

    L = instance.max_ride_time
    T = instance.max_route_duration
    B = list(e)
    # Bellman-Ford needs at most |V| relaxation rounds; the generous multiple
    # keeps float chatter from being mistaken for non-convergence.
    passes = max_passes if max_passes is not None else 4 * (m + 2)
    tol = 1e-12

    for _ in range(passes):
        changed = False
        for i in range(1, m):
            v = B[i - 1] + svc[i - 1] + travel[i]
            if v > B[i] + tol:
                B[i] = v
                changed = True
        for p, q in pairs:
            v = B[q] - svc[p] - L
            if v > B[p] + tol:
                B[p] = v  # a rider cannot board earlier than L before their drop-off
                changed = True
        v = B[m - 1] - T
        if v > B[0] + tol:
            B[0] = v  # leave the depot later to absorb waiting into the duration
            changed = True
        for i in range(m):
            if B[i] > l[i]:
                return None  # the minimal schedule already blows a window: infeasible
        if not changed:
            return B
    return None  # no fixpoint within the budget; report as unschedulable, never guess


def _schedule_from_hint(instance, seq: list[int], hint: dict[int, float], departure: float) -> list[float]:
    """Exact float forward schedule for `seq` that honours CP-SAT's chosen times
    as per-stop LOWER bounds.

    The as-early schedule the heuristic scheduler starts from discards the one
    thing the lattice solution actually knows: where the vehicle deliberately
    waits so a later rider's ride-time ceiling is met. Replaying those times as
    lower bounds -- while recomputing every arrival with EXACT float distances --
    turns a lattice-feasible answer into a candidate the exact checker can judge
    on its merits. It is still only a candidate: the caller verifies it, and a
    schedule this produces is discarded if the independent checker objects.
    """
    nodes = instance.nodes
    m = len(seq)
    begin = [0.0] * m
    begin[0] = max(nodes[seq[0]].tw_start, departure)
    for i in range(1, m):
        prev = seq[i - 1]
        arrival = begin[i - 1] + nodes[prev].service_duration + instance.dist(prev, seq[i])
        begin[i] = max(arrival, nodes[seq[i]].tw_start, hint.get(seq[i], 0.0))
    return begin


def _route_ok(instance: DarpInstance, seq: list[int], begin: list[float]) -> bool:
    """Is this one route exactly feasible? Judged by the INDEPENDENT checker on a
    single-route solution, not by a second copy of the constraint logic living
    here -- a private re-implementation is exactly how a checker and a solver
    drift into agreeing with each other and no one else. The checker treats an
    unserved request as uncovered rather than violated, which is what makes a
    per-route verdict meaningful."""
    probe = DarpSolution(
        instance_name=instance.name,
        num_requests=instance.num_requests,
        routes=(DarpRoute(
            vehicle=0,
            visits=tuple(DarpVisit(node_index=s, begin_service=begin[k]) for k, s in enumerate(seq)),
        ),),
        status="probe",
        objective=None,
        served_requests=(),
        solver_name=CPSAT_DARP_SOLVER_NAME,
        solver_version=CPSAT_DARP_SOLVER_VERSION,
        seed=0,
    )
    return not check_darp_feasibility(instance, probe)


def _verify_and_build(instance, sequences, seed, bound, proved, hints, depot_departures):
    """Validate CP-SAT's routing against the TRUE instance. Two schedules are
    tried -- CP-SAT's own times replayed exactly, then the independent heuristic
    scheduler -- and whichever the INDEPENDENT checker accepts is used. The
    relaxation's own verdict is never trusted; only the checker's counts."""
    routes: list[DarpRoute] = []
    for vi, seq in enumerate(sequences):
        candidates = [
            exact_schedule(instance, seq),
            _schedule_from_hint(instance, seq, hints, depot_departures.get(seq[1], 0.0)),
            schedule_route(instance, seq),
        ]
        begin = next((c for c in candidates if c is not None and _route_ok(instance, seq, c)), None)
        if begin is None:
            return (
                None,
                True,
                f"CP-SAT routing rejected on route {vi}: no exactly-feasible schedule found for "
                f"the sequence (the floored-travel-time model is a relaxation, so its route need "
                f"not be feasible for the true instance). Bound remains valid.",
            )
        routes.append(
            DarpRoute(
                vehicle=vi,
                visits=tuple(DarpVisit(node_index=s, begin_service=begin[k]) for k, s in enumerate(seq)),
            )
        )

    served = sorted({s for seq in sequences for s in seq if instance.is_pickup(s)})
    full = len(served) == instance.num_requests
    objective = sum(route_distance(instance, seq) for seq in sequences)
    solution = DarpSolution(
        instance_name=instance.name,
        num_requests=instance.num_requests,
        routes=tuple(routes),
        # NEVER "optimal" on the model's say-so. `certified_optimal` on the
        # outcome is the only place an optimality claim is computed, and it
        # requires the exactly-verified distance to meet the rigorous bound.
        status="feasible" if full else "incomplete",
        objective=objective if full else None,
        served_requests=tuple(served),
        solver_name=CPSAT_DARP_SOLVER_NAME,
        solver_version=CPSAT_DARP_SOLVER_VERSION,
        seed=seed,
    )
    violations = check_darp_feasibility(instance, solution)
    if violations:
        return (
            None,
            True,
            f"CP-SAT routing rejected by the INDEPENDENT checker: {violations[:3]}. Bound remains valid.",
        )
    kind = "model-optimal" if proved else "incumbent"
    return solution, False, f"CP-SAT {kind} routing, exactly verified by both checkers"
