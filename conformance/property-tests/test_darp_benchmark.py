"""Program F (DARP routing extension) conformance.

Three properties, mirroring the v0.1 decide contract on the routing IR:

1. The Cordeau-format loader parses an instance correctly (a self-contained
   synthetic instance always; the real acquired a2-16 when the benchmark archive
   is present, else skipped cleanly).
2. The heuristic produces a solution the INDEPENDENT routing checker accepts, and
   that also passes the original v0.1 `check_feasibility` via projection -- on a
   real acquired instance when available.
3. The independent checker NEVER accepts an infeasible routed solution. Every
   infeasible solution here is hand-built (the solver is not called to produce
   the thing under test), so a passing test is evidence of genuine independence:
   the checker rejects a bad route whoever wrote it.

Tests that need the benchmark archive skip cleanly when it was not acquired.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from packages.canonical.vocab import ReasonCode
from packages.decide.darp_bridge import project_darp_solution
from packages.decide.darp_ir import DarpInstance, DarpRoute, DarpSolution, DarpVisit
from packages.decide.darp_loader import (
    find_benchmark_archive,
    load_zip_instance,
    parse_instance,
)
from packages.decide.feasibility import (
    MalformedDarpSolution,
    check_darp_feasibility,
    check_feasibility,
    darp_objective,
    is_darp_feasible,
)
from packages.decide.darp_solver import schedule_route, solve_darp

_ARCHIVE = find_benchmark_archive()
_needs_archive = pytest.mark.skipif(_ARCHIVE is None, reason="Cordeau DARP benchmark archive not acquired")

# A tiny, self-contained Cordeau-format instance: 1 vehicle, 2 requests, capacity
# 2, on a vertical line so a feasible route is easy to reason about by hand.
_SYNTH = """1 2 480 2 60
0 0 0 0 0 0 480
1 0 1 1 1 0 480
2 0 2 1 1 0 480
3 0 3 1 -1 0 480
4 0 4 1 -1 0 480
5 0 0 0 0 0 480
"""

# Capacity-1 variant: two riders cannot be aboard together.
_SYNTH_CAP1 = """1 2 480 1 60
0 0 0 0 0 0 480
1 0 1 1 1 0 480
2 0 2 1 1 0 480
3 0 3 1 -1 0 480
4 0 4 1 -1 0 480
5 0 0 0 0 0 480
"""


def _synth() -> DarpInstance:
    return parse_instance(_SYNTH, name="synth")


def _solution(instance: DarpInstance, seq_and_times: list[tuple[int, float]], status: str = "feasible") -> DarpSolution:
    """Build a single-vehicle DarpSolution by hand from (node, begin) pairs."""
    visits = tuple(DarpVisit(node_index=nd, begin_service=t) for nd, t in seq_and_times)
    served = tuple(sorted({v.node_index for v in visits if instance.is_pickup(v.node_index)}))
    return DarpSolution(
        instance_name=instance.name,
        num_requests=instance.num_requests,
        routes=(DarpRoute(vehicle=0, visits=visits),),
        status=status,
        objective=None,
        served_requests=served,
        solver_name="hand-crafted",
        solver_version="0",
        seed=0,
    )


# --- 1. loader ------------------------------------------------------------

def test_loader_parses_synthetic_instance() -> None:
    inst = _synth()
    assert (inst.num_vehicles, inst.num_requests) == (1, 2)
    assert inst.max_route_duration == 480.0
    assert inst.vehicle_capacity == 2
    assert inst.max_ride_time == 60.0
    assert len(inst.nodes) == 2 * inst.num_requests + 2  # depot + 2n + depot
    assert inst.nodes[inst.pickup_index(1)].load == 1
    assert inst.nodes[inst.dropoff_index(1)].load == -1
    # travel time == Euclidean distance
    assert inst.dist(0, 4) == pytest.approx(4.0)


@_needs_archive
def test_loader_parses_real_a2_16() -> None:
    inst = load_zip_instance(_ARCHIVE, "a2-16")
    assert (inst.num_vehicles, inst.num_requests) == (2, 16)
    assert inst.vehicle_capacity == 3
    assert inst.max_ride_time == 30.0
    assert inst.max_route_duration == 480.0
    assert len(inst.nodes) == 34
    # a known coordinate from the published file (pickup node 1).
    assert inst.nodes[1].x == pytest.approx(-1.198)
    assert inst.nodes[1].y == pytest.approx(-5.164)


def test_best_known_values_are_intact() -> None:
    """Guard the cited reference numbers against accidental corruption."""
    data = json.loads((Path(__file__).resolve().parents[2] / "benchmarks" / "quality" / "best_known.json").read_text(encoding="utf-8"))
    inst = data["instances"]
    assert inst["a2-16"] == {"best_known": 294.25, "proven_optimal": True}
    assert inst["a4-16"]["best_known"] == 282.68 and inst["a4-16"]["proven_optimal"] is True
    assert inst["a4-48"]["proven_optimal"] is False  # best-known, not proven optimum


# --- 2. heuristic produces a solution both checkers accept -----------------

def test_hand_built_feasible_solution_is_accepted_by_both_checkers() -> None:
    inst = _synth()
    # 0 -> p1 -> p2 -> d1 -> d2 -> depot, scheduled as-early.
    begin = schedule_route(inst, [0, 1, 2, 3, 4, 5])
    assert begin is not None
    sol = _solution(inst, list(zip([0, 1, 2, 3, 4, 5], begin)))
    assert check_darp_feasibility(inst, sol) == []
    assert is_darp_feasible(inst, sol)
    # The original v0.1 checker must also accept the projection.
    problem, projected = project_darp_solution(inst, sol)
    assert check_feasibility(problem, projected) == []
    # objective recomputed independently equals the route distance.
    assert darp_objective(inst, sol) == pytest.approx(1 + 1 + 1 + 1 + 4)


@_needs_archive
def test_solver_solution_on_real_instance_passes_both_checkers() -> None:
    inst = load_zip_instance(_ARCHIVE, "a2-16")
    sol = solve_darp(inst, seed=1, max_iterations=80, time_limit_s=40)
    # Solver self-audits, but re-check independently here too.
    assert check_darp_feasibility(inst, sol) == []
    problem, projected = project_darp_solution(inst, sol)
    assert check_feasibility(problem, projected) == []
    # Objective is a real, positive routing distance; gap is honest (>= 0 vs a
    # proven optimum -- a heuristic cannot beat it).
    if sol.status == "feasible":
        assert darp_objective(inst, sol) >= 294.25 - 1e-6


# --- 3. the checker never accepts an infeasible routed solution -----------

def test_time_window_violation_is_rejected() -> None:
    inst = _synth()
    # Drop-off of request 1 (node 3) begins at 500, past its window end 480.
    sol = _solution(inst, [(0, 0.0), (1, 1.0), (3, 500.0), (5, 501.0)])
    codes = {v.code for v in check_darp_feasibility(inst, sol)}
    assert ReasonCode.DROPOFF_WINDOW in codes
    assert not is_darp_feasible(inst, sol)


def test_ride_time_violation_is_rejected() -> None:
    inst = _synth()  # L = 60
    # Travel-consistent, in-window schedule, but ride time of request 1 is
    # 400 - (1 + 1) = 398 > 60.
    sol = _solution(inst, [(0, 0.0), (1, 1.0), (3, 400.0), (5, 405.0)])
    codes = {v.code for v in check_darp_feasibility(inst, sol)}
    assert ReasonCode.MAX_RIDE_TIME in codes


def test_travel_time_inconsistency_is_rejected() -> None:
    inst = _synth()
    # Begin service at node 4 (dist 4 from depot, plus node 1's service/leg) far too
    # early to be physically reachable.
    sol = _solution(inst, [(0, 0.0), (1, 1.0), (2, 2.0), (3, 3.0), (4, 3.1), (5, 3.2)])
    codes = {v.code for v in check_darp_feasibility(inst, sol)}
    assert ReasonCode.PRECEDENCE in codes  # arrival precedes earliest reachable time


def test_capacity_overload_is_rejected() -> None:
    inst = parse_instance(_SYNTH_CAP1, name="cap1")  # capacity 1
    # Both riders aboard at once: 0 -> p1 -> p2 -> d1 -> d2 -> depot with load 2 > 1.
    begin = [0.0, 1.0, 2.0, 3.0, 4.0, 8.0]
    sol = _solution(inst, list(zip([0, 1, 2, 3, 4, 5], begin)))
    codes = {v.code for v in check_darp_feasibility(inst, sol)}
    assert ReasonCode.NO_ACCESSIBLE_CAPACITY in codes


def test_dropoff_before_pickup_is_rejected() -> None:
    inst = _synth()
    # Request 1's drop-off (node 3) visited before its pickup (node 1).
    sol = _solution(inst, [(0, 0.0), (3, 1.0), (1, 2.0), (5, 3.0)])
    codes = {v.code for v in check_darp_feasibility(inst, sol)}
    assert ReasonCode.PRECEDENCE in codes


def test_route_not_anchored_at_depot_is_malformed() -> None:
    inst = _synth()
    sol = _solution(inst, [(1, 0.0), (3, 5.0)])  # starts at a pickup, not the depot
    with pytest.raises(MalformedDarpSolution):
        check_darp_feasibility(inst, sol)


def test_node_visited_twice_is_malformed() -> None:
    inst = _synth()
    sol = _solution(inst, [(0, 0.0), (1, 1.0), (1, 2.0), (3, 3.0), (5, 4.0)])
    with pytest.raises(MalformedDarpSolution):
        check_darp_feasibility(inst, sol)


@pytest.mark.parametrize("trial", range(30))
def test_property_checker_never_accepts_a_capacity_overload(trial: int) -> None:
    """Randomly pack more simultaneous riders than a capacity-1 vehicle can hold;
    the checker must ALWAYS surface a capacity violation. Solutions hand-built."""
    rng = random.Random(4000 + trial)
    inst = parse_instance(_SYNTH_CAP1, name="cap1")
    # Both requests aboard together (pickups before any drop-off) -> load 2 > 1.
    order = [0, 1, 2, 3, 4, 5]
    t = 0.0
    times = []
    for _ in order:
        times.append(t)
        t += rng.uniform(1.0, 5.0)
    sol = _solution(inst, list(zip(order, times)))
    assert not is_darp_feasible(inst, sol)
    assert ReasonCode.NO_ACCESSIBLE_CAPACITY in {v.code for v in check_darp_feasibility(inst, sol)}


@_needs_archive
@pytest.mark.parametrize("trial", range(3))
def test_property_perturbing_a_real_solution_infeasible_is_caught(trial: int) -> None:
    """Take a genuine solver solution on a real instance and shove one drop-off
    far past its window; the independent checker must catch it."""
    inst = load_zip_instance(_ARCHIVE, "a2-16")
    sol = solve_darp(inst, seed=trial, max_iterations=40, time_limit_s=20)
    assert is_darp_feasible(inst, sol)  # the real solution is feasible
    # Corrupt the first non-depot visit's time to blow its window.
    routes = list(sol.routes)
    for ri, route in enumerate(routes):
        visits = list(route.visits)
        for vi, v in enumerate(visits):
            if v.node_index not in (inst.depot_start, inst.depot_end):
                visits[vi] = DarpVisit(node_index=v.node_index, begin_service=v.begin_service + 100000.0)
                routes[ri] = DarpRoute(vehicle=route.vehicle, visits=tuple(visits))
                broken = DarpSolution(
                    instance_name=sol.instance_name, num_requests=sol.num_requests,
                    routes=tuple(routes), status=sol.status, objective=sol.objective,
                    served_requests=sol.served_requests, solver_name=sol.solver_name,
                    solver_version=sol.solver_version, seed=sol.seed,
                )
                assert not is_darp_feasible(inst, broken)
                return
