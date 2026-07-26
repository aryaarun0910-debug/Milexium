"""Program F conformance: the Decide solver reports an honest status and every
solution it accepts is accepted by the INDEPENDENT feasibility checker.

These are the blueprint 06 + 14 contract properties for the candidate generator:
a feasible plan the independent checker signs off on, an honest optimal/feasible/
infeasible/timeout status, and -- the failure mode blueprint 15 names -- a
timeout incumbent that is NEVER labelled optimal. No hypothesis dependency; the
property tests drive many seeded random instances with the stdlib `random`.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from themis.canonical import PolicyId, RequestId, TenantId, VehicleId, new_id
from themis.canonical.vocab import ReasonCode, ScheduleRunStatus
from metis.decide import (
    DecisionPolicy,
    DecisionProblem,
    DecisionVehicle,
    RideRequest,
    is_feasible,
    solve,
)

_BASE = datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc)


def _at(minute: int) -> datetime:
    return _BASE + timedelta(minutes=minute)


def _policy(**kw) -> DecisionPolicy:
    return DecisionPolicy(policy_id=new_id(PolicyId), name="test", **kw)


def _vehicle(amb: int, wc: int, shift_minutes: int = 240) -> DecisionVehicle:
    return DecisionVehicle(
        vehicle_id=new_id(VehicleId),
        capacity_ambulatory=amb,
        capacity_wheelchair=wc,
        shift_start=_BASE,
        shift_end=_BASE + timedelta(minutes=shift_minutes),
    )


def test_solver_produces_a_feasible_optimal_plan_the_checker_accepts() -> None:
    problem = DecisionProblem(
        tenant_id=new_id(TenantId),
        policy=_policy(),
        vehicles=(_vehicle(2, 1),),
        requests=(
            RideRequest(request_id=new_id(RequestId), pickup_window_start=_at(0), pickup_window_end=_at(30), dropoff_window_end=_at(90), nominal_ride_time_minutes=20, max_ride_time_minutes=40),
            RideRequest(request_id=new_id(RequestId), pickup_window_start=_at(10), pickup_window_end=_at(40), dropoff_window_end=_at(90), needs_wheelchair=True, nominal_ride_time_minutes=15, max_ride_time_minutes=30),
        ),
    )
    solution = solve(problem, seed=7)

    assert solution.status is ScheduleRunStatus.OPTIMAL
    assert len(solution.assignments) == 2
    assert solution.unserved == ()
    # An OPTIMAL claim carries a real gap-0 certificate and a bound.
    assert solution.gap == 0.0
    assert solution.bound == solution.objective_value
    assert solution.proven_optimal is True
    # The independent checker must accept it.
    assert is_feasible(problem, solution)


def test_solution_is_deterministic_for_a_fixed_seed() -> None:
    problem = DecisionProblem(
        tenant_id=new_id(TenantId),
        policy=_policy(exact_max_requests=2),  # force the greedy backend where seed matters
        vehicles=(_vehicle(2, 0),),
        requests=tuple(
            RideRequest(request_id=new_id(RequestId), pickup_window_start=_at(i * 5), pickup_window_end=_at(60), dropoff_window_end=_at(120), nominal_ride_time_minutes=15, max_ride_time_minutes=45)
            for i in range(5)
        ),
    )
    first = solve(problem, seed=99)
    second = solve(problem, seed=99)
    assert first.model_dump() == second.model_dump()
    assert first.status is ScheduleRunStatus.FEASIBLE
    # Greedy is honest: feasible, never proven optimal.
    assert first.proven_optimal is False
    assert first.bound is None and first.gap is None


def test_mandated_request_that_cannot_fit_yields_infeasible_not_optimal() -> None:
    """Two must-serve wheelchair riders with overlapping mandatory windows and a
    single wheelchair position, no alternative vehicle -> proven INFEASIBLE."""
    problem = DecisionProblem(
        tenant_id=new_id(TenantId),
        policy=_policy(),
        vehicles=(_vehicle(4, 1),),
        requests=(
            RideRequest(request_id=new_id(RequestId), pickup_window_start=_at(0), pickup_window_end=_at(5), dropoff_window_end=_at(60), needs_wheelchair=True, nominal_ride_time_minutes=40, max_ride_time_minutes=60, must_serve=True),
            RideRequest(request_id=new_id(RequestId), pickup_window_start=_at(0), pickup_window_end=_at(5), dropoff_window_end=_at(60), needs_wheelchair=True, nominal_ride_time_minutes=40, max_ride_time_minutes=60, must_serve=True),
        ),
    )
    solution = solve(problem)

    assert solution.status is ScheduleRunStatus.INFEASIBLE
    assert solution.proven_optimal is False
    assert solution.assignments == ()  # no plan is accepted
    assert solution.objective_value is None and solution.gap is None


def test_timeout_reports_timeout_and_never_optimal() -> None:
    """A tiny node budget makes the exact backend run out of search before it can
    prove anything. It must report TIMEOUT with a still-feasible incumbent, never
    an optimal label (blueprint 15: 'solver timeout returned as valid optimal
    plan')."""
    problem = DecisionProblem(
        tenant_id=new_id(TenantId),
        policy=_policy(max_search_nodes=3),
        vehicles=(_vehicle(1, 0),),
        requests=tuple(
            RideRequest(request_id=new_id(RequestId), pickup_window_start=_at(0), pickup_window_end=_at(120), dropoff_window_end=_at(180), nominal_ride_time_minutes=20, max_ride_time_minutes=60, must_serve=False)
            for _ in range(6)
        ),
    )
    solution = solve(problem)

    assert solution.status is ScheduleRunStatus.TIMEOUT
    assert solution.status is not ScheduleRunStatus.OPTIMAL
    assert solution.proven_optimal is False
    # A timeout makes no optimality claim: no bound, no gap.
    assert solution.bound is None and solution.gap is None
    # Whatever incumbent it kept must itself be feasible.
    assert is_feasible(problem, solution)
    # Requests it could not resolve are denied SOLVER_TIMEOUT.
    if solution.unserved:
        assert any(ReasonCode.SOLVER_TIMEOUT in d.reason_codes for d in solution.unserved)


def test_wheelchair_request_with_no_accessible_vehicle_is_denied_with_reason() -> None:
    wc_request = RideRequest(request_id=new_id(RequestId), pickup_window_start=_at(0), pickup_window_end=_at(30), dropoff_window_end=_at(90), needs_wheelchair=True, nominal_ride_time_minutes=20, max_ride_time_minutes=40, must_serve=False)
    problem = DecisionProblem(
        tenant_id=new_id(TenantId),
        policy=_policy(),
        vehicles=(_vehicle(4, 0),),  # ambulatory-only fleet
        requests=(wc_request,),
    )
    solution = solve(problem)

    assert solution.assignments == ()
    assert len(solution.unserved) == 1
    assert ReasonCode.NO_ACCESSIBLE_CAPACITY in solution.unserved[0].reason_codes


def _random_instance(rng: random.Random) -> DecisionProblem:
    n_vehicles = rng.randint(1, 3)
    vehicles = tuple(_vehicle(rng.randint(1, 3), rng.randint(0, 2), shift_minutes=240) for _ in range(n_vehicles))
    n_requests = rng.randint(1, 5)
    requests = []
    for _ in range(n_requests):
        start = rng.randint(0, 120)
        requests.append(
            RideRequest(
                request_id=new_id(RequestId),
                pickup_window_start=_at(start),
                pickup_window_end=_at(start + rng.randint(5, 40)),
                dropoff_window_end=_at(start + rng.randint(40, 120)),
                needs_wheelchair=rng.random() < 0.3,
                party_size=rng.randint(1, 2),
                nominal_ride_time_minutes=rng.randint(5, 40),
                max_ride_time_minutes=rng.randint(20, 90),
                must_serve=rng.random() < 0.5,
            )
        )
    return DecisionProblem(tenant_id=new_id(TenantId), policy=_policy(), vehicles=vehicles, requests=tuple(requests))


@pytest.mark.parametrize("trial", range(60))
def test_property_every_solver_output_is_accepted_by_the_independent_checker(trial: int) -> None:
    """For many random instances, whatever the solver accepts is feasible, and it
    never contradicts its own status: OPTIMAL implies a gap-0 certificate;
    anything else makes no optimality claim."""
    rng = random.Random(trial)
    problem = _random_instance(rng)
    solution = solve(problem, seed=trial)

    assert is_feasible(problem, solution)  # accepted assignments never break a hard constraint
    if solution.status is ScheduleRunStatus.OPTIMAL:
        assert solution.gap == 0.0 and solution.bound is not None
    else:
        assert solution.proven_optimal is False
    # An OPTIMAL plan that silently drops a mandate is a bug: a proven optimum
    # would have reported INFEASIBLE instead. (Greedy FEASIBLE may leave a
    # mandate unserved -- it never claims to have proven anything.)
    if solution.status is ScheduleRunStatus.OPTIMAL:
        served = {str(a.request_id) for a in solution.assignments}
        assert all(str(r.request_id) in served for r in problem.requests if r.must_serve)
