"""Projection from a routed DARP solution onto the v0.1 Decision IR.

The Phase-2 integrity contract requires that *every* reported benchmark solution
also passes the original, unmodified independent checker
(`packages.decide.feasibility.check_feasibility`). That checker speaks the v0.1
IR (`RideRequest` / `DecisionVehicle` / `Assignment`), not the routing IR, so
this module faithfully re-expresses a routed solution in that vocabulary and
lets the existing checker re-derive -- a second, independent time -- the
per-request and capacity constraints it understands.

The mapping is exact, not gerrymandered to pass:

- A request's assignment `pickup_time` is its *departure* from the pickup node
  (begin-service + service duration = D_i); `dropoff_time` is begin-service at
  the drop-off (B_{n+i}). The onboard interval [D_i, B_{n+i}] is then exactly
  when the rider occupies a seat, so the existing capacity sweep re-checks the
  true DARP load, and `dropoff_time - pickup_time` is exactly the DARP ride time.
- The pickup time window [e_i, l_i] (a bound on begin-service B_i) is
  re-expressed on the departure D_i = B_i + d_i as [e_i + d_i, l_i + d_i]; the
  drop-off window maps straight through onto B_{n+i}.
- `max_ride_time` is the instance L; capacity maps to the ambulatory seat count
  (Q), party size to the node load q_i; the vehicle shift is the depot window
  [e_0, l_0], so the existing SHIFT_END check re-verifies route completion.

Only *served* requests are projected -- the existing checker's contract is "no
accepted assignment breaks a hard constraint", and an unserved request has no
assignment to check. This module imports both IRs; the checker it feeds does
not import any solver.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from packages.canonical.ids import PolicyId, TenantId, VehicleId, RequestId, new_id
from packages.decide.darp_ir import DarpInstance, DarpSolution
from packages.decide.ir import (
    Assignment,
    DecisionPolicy,
    DecisionProblem,
    DecisionSolution,
    DecisionVehicle,
    RideRequest,
)
from packages.canonical.vocab import ScheduleRunStatus

# A fixed epoch to carry float-minute schedules into the datetime-typed v0.1 IR.
_EPOCH = datetime(2020, 1, 1, tzinfo=timezone.utc)


def _t(minutes: float) -> datetime:
    return _EPOCH + timedelta(minutes=minutes)


def project_darp_solution(
    instance: DarpInstance, solution: DarpSolution
) -> tuple[DecisionProblem, DecisionSolution]:
    """Re-express the served portion of a routed DARP solution in the v0.1 IR so
    `packages.decide.feasibility.check_feasibility` can validate it unchanged."""
    n = instance.num_requests
    depot_ids = {instance.depot_start, instance.depot_end}

    # begin-service time per served node, and which vehicle served each request.
    begin: dict[int, float] = {}
    request_vehicle: dict[int, VehicleId] = {}
    vehicle_ids: dict[int, VehicleId] = {}
    for route in solution.routes:
        if route.vehicle not in vehicle_ids:
            vehicle_ids[route.vehicle] = new_id(VehicleId)
        for v in route.visits:
            if v.node_index in depot_ids:
                continue
            begin[v.node_index] = v.begin_service
            if instance.is_pickup(v.node_index):
                request_vehicle[instance.request_of(v.node_index)] = vehicle_ids[route.vehicle]

    depot = instance.nodes[instance.depot_start]
    shift_start, shift_end = _t(depot.tw_start), _t(depot.tw_end)
    vehicles = tuple(
        DecisionVehicle(
            vehicle_id=vid,
            capacity_ambulatory=instance.vehicle_capacity,
            capacity_wheelchair=0,
            shift_start=shift_start,
            shift_end=shift_end,
        )
        for vid in vehicle_ids.values()
    )

    requests: list[RideRequest] = []
    assignments: list[Assignment] = []
    for r in range(1, n + 1):
        p = instance.pickup_index(r)
        d = instance.dropoff_index(r)
        if p not in begin or d not in begin:
            continue  # unserved request -- nothing to assign or check
        p_node, d_node = instance.nodes[p], instance.nodes[d]
        rid = new_id(RequestId)
        depart_pickup = begin[p] + p_node.service_duration
        direct = instance.dist(p, d)
        requests.append(
            RideRequest(
                request_id=rid,
                pickup_window_start=_t(p_node.tw_start + p_node.service_duration),
                pickup_window_end=_t(p_node.tw_end + p_node.service_duration),
                dropoff_window_start=_t(d_node.tw_start),
                dropoff_window_end=_t(d_node.tw_end),
                needs_wheelchair=False,
                party_size=p_node.load,
                nominal_ride_time_minutes=max(direct, 1e-6),
                max_ride_time_minutes=instance.max_ride_time,
                must_serve=True,
            )
        )
        assignments.append(
            Assignment(
                request_id=rid,
                vehicle_id=request_vehicle[r],
                pickup_time=_t(depart_pickup),
                dropoff_time=_t(begin[d]),
            )
        )

    problem = DecisionProblem(
        tenant_id=new_id(TenantId),
        policy=DecisionPolicy(policy_id=new_id(PolicyId), name=f"darp-projection-{instance.name}"),
        vehicles=vehicles,
        requests=tuple(requests),
    )
    projected = DecisionSolution(
        status=ScheduleRunStatus.FEASIBLE,
        assignments=tuple(assignments),
        unserved=(),
        objective_value=None,
        bound=None,
        gap=None,
        seed=solution.seed,
        solver_name=solution.solver_name,
        solver_version=solution.solver_version,
    )
    return problem, projected
