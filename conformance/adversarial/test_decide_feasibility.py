"""Program F adversarial conformance: the INDEPENDENT feasibility checker rejects
infeasible solutions -- including hand-crafted ones the solver never produced.

This is the whole point of the generator/checker separation (blueprint 06, the
same discipline as packages.verify vs packages.canonical): the checker must
catch a hard-constraint violation no matter who wrote the solution, and it must
never accept a capacity breach. Every DecisionSolution here is built BY HAND
(the solver is not called to produce the thing under test) so a passing test is
evidence of genuine independence, not of the solver checking its own work.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from packages.canonical import PolicyId, RequestId, TenantId, VehicleId, new_id
from packages.canonical.vocab import ReasonCode, ScheduleRunStatus
from packages.decide import (
    Assignment,
    DecisionPolicy,
    DecisionProblem,
    DecisionSolution,
    DecisionVehicle,
    Denial,
    MalformedSolution,
    RideRequest,
    check_feasibility,
    is_feasible,
)

_BASE = datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc)


def _at(minute: int) -> datetime:
    return _BASE + timedelta(minutes=minute)


def _policy() -> DecisionPolicy:
    return DecisionPolicy(policy_id=new_id(PolicyId), name="adv")


def _vehicle(amb: int, wc: int, shift_minutes: int = 240) -> DecisionVehicle:
    return DecisionVehicle(vehicle_id=new_id(VehicleId), capacity_ambulatory=amb, capacity_wheelchair=wc, shift_start=_BASE, shift_end=_BASE + timedelta(minutes=shift_minutes))


def _hand_solution(*assignments: Assignment) -> DecisionSolution:
    """A DecisionSolution the solver never produced -- deliberately labelled
    OPTIMAL to prove the checker validates the assignments, not the label."""
    return DecisionSolution(status=ScheduleRunStatus.OPTIMAL, assignments=assignments, unserved=(), objective_value=0.0, bound=0.0, gap=0.0, seed=0, solver_name="hand-crafted", solver_version="0")


def _codes(problem, solution) -> set[ReasonCode]:
    return {v.code for v in check_feasibility(problem, solution)}


def test_pickup_outside_window_is_rejected() -> None:
    req = RideRequest(request_id=new_id(RequestId), pickup_window_start=_at(0), pickup_window_end=_at(20), dropoff_window_end=_at(120), nominal_ride_time_minutes=20, max_ride_time_minutes=60)
    veh = _vehicle(2, 0)
    problem = DecisionProblem(tenant_id=new_id(TenantId), policy=_policy(), vehicles=(veh,), requests=(req,))
    # Pickup at minute 40, well past the 20-minute window end.
    solution = _hand_solution(Assignment(request_id=req.request_id, vehicle_id=veh.vehicle_id, pickup_time=_at(40), dropoff_time=_at(60)))
    assert ReasonCode.PICKUP_WINDOW in _codes(problem, solution)
    assert not is_feasible(problem, solution)


def test_dropoff_after_latest_window_is_rejected() -> None:
    req = RideRequest(request_id=new_id(RequestId), pickup_window_start=_at(0), pickup_window_end=_at(30), dropoff_window_end=_at(40), nominal_ride_time_minutes=20, max_ride_time_minutes=60)
    veh = _vehicle(2, 0)
    problem = DecisionProblem(tenant_id=new_id(TenantId), policy=_policy(), vehicles=(veh,), requests=(req,))
    # Dropoff at minute 50, past the 40-minute latest-dropoff.
    solution = _hand_solution(Assignment(request_id=req.request_id, vehicle_id=veh.vehicle_id, pickup_time=_at(30), dropoff_time=_at(50)))
    assert ReasonCode.DROPOFF_WINDOW in _codes(problem, solution)


def test_precedence_violation_pickup_after_dropoff_is_rejected() -> None:
    req = RideRequest(request_id=new_id(RequestId), pickup_window_start=_at(0), pickup_window_end=_at(60), dropoff_window_end=_at(120), nominal_ride_time_minutes=20, max_ride_time_minutes=60)
    veh = _vehicle(2, 0)
    problem = DecisionProblem(tenant_id=new_id(TenantId), policy=_policy(), vehicles=(veh,), requests=(req,))
    # Dropoff before pickup.
    solution = _hand_solution(Assignment(request_id=req.request_id, vehicle_id=veh.vehicle_id, pickup_time=_at(30), dropoff_time=_at(10)))
    assert ReasonCode.PRECEDENCE in _codes(problem, solution)


def test_max_ride_time_breach_is_rejected() -> None:
    req = RideRequest(request_id=new_id(RequestId), pickup_window_start=_at(0), pickup_window_end=_at(30), dropoff_window_end=_at(120), nominal_ride_time_minutes=20, max_ride_time_minutes=25)
    veh = _vehicle(2, 0)
    problem = DecisionProblem(tenant_id=new_id(TenantId), policy=_policy(), vehicles=(veh,), requests=(req,))
    # 50-minute ride against a 25-minute ceiling.
    solution = _hand_solution(Assignment(request_id=req.request_id, vehicle_id=veh.vehicle_id, pickup_time=_at(0), dropoff_time=_at(50)))
    assert ReasonCode.MAX_RIDE_TIME in _codes(problem, solution)


def test_shift_overrun_is_rejected() -> None:
    req = RideRequest(request_id=new_id(RequestId), pickup_window_start=_at(0), pickup_window_end=_at(300), dropoff_window_end=_at(400), nominal_ride_time_minutes=30, max_ride_time_minutes=60)
    veh = _vehicle(2, 0, shift_minutes=120)  # shift ends at minute 120
    problem = DecisionProblem(tenant_id=new_id(TenantId), policy=_policy(), vehicles=(veh,), requests=(req,))
    # Dropoff at minute 210, an hour and a half past the shift end.
    solution = _hand_solution(Assignment(request_id=req.request_id, vehicle_id=veh.vehicle_id, pickup_time=_at(180), dropoff_time=_at(210)))
    assert ReasonCode.SHIFT_END in _codes(problem, solution)


def test_wheelchair_request_on_a_non_accessible_vehicle_is_rejected() -> None:
    req = RideRequest(request_id=new_id(RequestId), pickup_window_start=_at(0), pickup_window_end=_at(30), dropoff_window_end=_at(120), needs_wheelchair=True, nominal_ride_time_minutes=20, max_ride_time_minutes=60)
    veh = _vehicle(4, 0)  # no wheelchair capacity
    problem = DecisionProblem(tenant_id=new_id(TenantId), policy=_policy(), vehicles=(veh,), requests=(req,))
    solution = _hand_solution(Assignment(request_id=req.request_id, vehicle_id=veh.vehicle_id, pickup_time=_at(0), dropoff_time=_at(20)))
    assert ReasonCode.NO_ACCESSIBLE_CAPACITY in _codes(problem, solution)


def test_capacity_breach_from_overlapping_rides_is_rejected() -> None:
    r1 = RideRequest(request_id=new_id(RequestId), pickup_window_start=_at(0), pickup_window_end=_at(60), dropoff_window_end=_at(120), nominal_ride_time_minutes=30, max_ride_time_minutes=90)
    r2 = RideRequest(request_id=new_id(RequestId), pickup_window_start=_at(0), pickup_window_end=_at(60), dropoff_window_end=_at(120), nominal_ride_time_minutes=30, max_ride_time_minutes=90)
    veh = _vehicle(1, 0)  # one ambulatory seat
    problem = DecisionProblem(tenant_id=new_id(TenantId), policy=_policy(), vehicles=(veh,), requests=(r1, r2))
    # Both onboard from minute 10-30 -> load 2 on a 1-seat vehicle.
    solution = _hand_solution(
        Assignment(request_id=r1.request_id, vehicle_id=veh.vehicle_id, pickup_time=_at(0), dropoff_time=_at(30)),
        Assignment(request_id=r2.request_id, vehicle_id=veh.vehicle_id, pickup_time=_at(10), dropoff_time=_at(40)),
    )
    assert ReasonCode.NO_ACCESSIBLE_CAPACITY in _codes(problem, solution)
    assert not is_feasible(problem, solution)


def test_touching_intervals_do_not_count_as_overlap() -> None:
    """A dropoff frees the seat the instant it happens: rider B boarding exactly
    when rider A alights is within a one-seat capacity, not a breach."""
    r1 = RideRequest(request_id=new_id(RequestId), pickup_window_start=_at(0), pickup_window_end=_at(60), dropoff_window_end=_at(120), nominal_ride_time_minutes=30, max_ride_time_minutes=90)
    r2 = RideRequest(request_id=new_id(RequestId), pickup_window_start=_at(0), pickup_window_end=_at(60), dropoff_window_end=_at(120), nominal_ride_time_minutes=30, max_ride_time_minutes=90)
    veh = _vehicle(1, 0)
    problem = DecisionProblem(tenant_id=new_id(TenantId), policy=_policy(), vehicles=(veh,), requests=(r1, r2))
    solution = _hand_solution(
        Assignment(request_id=r1.request_id, vehicle_id=veh.vehicle_id, pickup_time=_at(0), dropoff_time=_at(30)),
        Assignment(request_id=r2.request_id, vehicle_id=veh.vehicle_id, pickup_time=_at(30), dropoff_time=_at(60)),
    )
    assert is_feasible(problem, solution)


def test_unknown_id_or_double_assignment_is_malformed_not_a_soft_violation() -> None:
    req = RideRequest(request_id=new_id(RequestId), pickup_window_start=_at(0), pickup_window_end=_at(60), dropoff_window_end=_at(120), nominal_ride_time_minutes=20, max_ride_time_minutes=60)
    veh = _vehicle(2, 0)
    problem = DecisionProblem(tenant_id=new_id(TenantId), policy=_policy(), vehicles=(veh,), requests=(req,))

    # Assignment references a request that is not in the problem.
    ghost = _hand_solution(Assignment(request_id=new_id(RequestId), vehicle_id=veh.vehicle_id, pickup_time=_at(0), dropoff_time=_at(20)))
    with pytest.raises(MalformedSolution):
        check_feasibility(problem, ghost)

    # Same request served and denied at once.
    contradictory = DecisionSolution(
        status=ScheduleRunStatus.OPTIMAL,
        assignments=(Assignment(request_id=req.request_id, vehicle_id=veh.vehicle_id, pickup_time=_at(0), dropoff_time=_at(20)),),
        unserved=(Denial(request_id=req.request_id, reason_codes=(ReasonCode.NO_ACCESSIBLE_CAPACITY,)),),
        objective_value=0.0, bound=0.0, gap=0.0, seed=0, solver_name="hand", solver_version="0",
    )
    with pytest.raises(MalformedSolution):
        check_feasibility(problem, contradictory)


@pytest.mark.parametrize("trial", range(50))
def test_property_checker_never_accepts_a_capacity_breach(trial: int) -> None:
    """Randomly pack more concurrent riders onto a vehicle than it can hold; the
    checker must ALWAYS surface a NO_ACCESSIBLE_CAPACITY violation. Solutions are
    hand-built, never solver-produced."""
    rng = random.Random(1000 + trial)
    capacity = rng.randint(1, 3)
    overload = capacity + rng.randint(1, 3)  # strictly more riders than seats, all overlapping
    veh = _vehicle(capacity, 0, shift_minutes=600)
    requests = []
    assignments = []
    common_pickup = rng.randint(0, 30)
    for _ in range(overload):
        req = RideRequest(request_id=new_id(RequestId), pickup_window_start=_at(0), pickup_window_end=_at(300), dropoff_window_end=_at(600), party_size=1, nominal_ride_time_minutes=60, max_ride_time_minutes=120)
        requests.append(req)
        # All board at the same instant and stay aboard together -> load == overload > capacity.
        assignments.append(Assignment(request_id=req.request_id, vehicle_id=veh.vehicle_id, pickup_time=_at(common_pickup), dropoff_time=_at(common_pickup + 60)))
    problem = DecisionProblem(tenant_id=new_id(TenantId), policy=_policy(), vehicles=(veh,), requests=tuple(requests))
    solution = _hand_solution(*assignments)

    assert not is_feasible(problem, solution)
    assert ReasonCode.NO_ACCESSIBLE_CAPACITY in _codes(problem, solution)
