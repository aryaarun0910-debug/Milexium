"""Pooling as a decision: plan the shares, then judge the plan by what it served.

WHY OCCUPANCY IS THE RIGHT TARGET. Across US agencies reporting passenger miles in
both 2015 and 2024, average trip length FELL 4.6% while occupancy fell 10.0%
(1.213 -> 1.092 passenger miles per vehicle mile); 66.8% of agencies lost
occupancy and the recovery has stalled. The productivity collapse is LOST
RIDE-SHARING. And occupancy is not a fact about riders that a forecaster
predicts -- it is the thing a scheduling system decides, one share at a time.
This module is where that decision is taken and where it is judged.

**RELEASING CAPACITY, NEVER RATIONING IT.** A pooling model that raised occupancy
by serving fewer riders would be a failure dressed as a result. Restricting
transit use is not the objective. Two things enforce that here rather than
promise it:

- The planner physically cannot decline a rider it could serve. If any vehicle
  admits a certified insertion and the policy returns nothing, the harness raises
  `metis.decide.online.RationingRefused` -- the SAME exception type the
  commingled online harness raises, imported rather than re-declared, so the two
  cannot drift apart. What varies between policies is WHERE a rider is placed,
  never WHETHER.
- Every evaluation reports trips served next to occupancy, stratified by
  accessibility requirement. An occupancy gain accompanied by a fall in trips
  served -- or by a fall in wheelchair trips served while ambulatory trips rise --
  is a defect report, and the metrics are shaped so that it cannot be hidden in an
  aggregate.

WHAT IS COMPARED, AND WHY THAT IS THE FAIR COMPARISON. The two policies run
through ONE harness, on ONE arrival order, with ONE feasibility authority. They
differ in a single term: `capacity_weight`.

    capacity_weight = 0   ->  cheapest certified insertion. This is the rule the
                             existing planner's insertion step already follows
                             (`darp_solver._scan_insertions` ranks by added
                             distance), so it is a faithful stand-in for current
                             practice inside this harness.
    capacity_weight > 0   ->  cheapest insertion AFTER charging it for the likely
                             future trips it forecloses, with accessible
                             foreclosure charged extra.

Isolating the term is the whole design. A comparison against the offline LNS or
CP-SAT solver would conflate the pooling objective with FORESIGHT -- those see
every request before committing to any -- and the resulting number would say
nothing about the capacity term. The offline optimum from ADR-0060 is still
reported, as a yardstick on distance and as the reminder that both online
policies are working with strictly less information.

STATUS. Cordeau instances are synthetic academic benchmarks and the accessibility
labels on them are ASSIGNED, not observed (ADR-0065;
`compatibility.ASSIGNED_ACCESSIBILITY_NOTE`). Everything here supports
ALGORITHMIC claims only -- that the decision changes, that the metrics
discriminate, that no accepted plan violates a hard constraint. Nothing here is
Validated and no number may be cited as evidence about a real fleet, its riders,
or their access to service.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from random import Random
from typing import Callable, Sequence

from metis.decide.capacity_value import (
    CapacityEnsemble,
    build_ensemble,
    empty_routes,
    prior_from_observed,
)
from metis.decide.compatibility import (
    ASSIGNED_ACCESSIBILITY_NOTE,
    AccessibilityProfile,
    Certificate,
    certify_insertion,
    check_equipment_feasibility,
    onboard_profile,
    route_passenger_miles,
    route_shared_vehicle_miles,
    solo_route,
)
from metis.decide.darp_ir import DarpInstance, DarpRoute, DarpSolution, DarpVisit
from metis.decide.darp_solver import route_distance
from metis.decide.feasibility import check_darp_feasibility
from metis.decide.online import RationingRefused

POOLING_PLANNER_NAME = "milexium-decide-pooling"
POOLING_PLANNER_VERSION = "0.5.0"

WHEELCHAIR = "wheelchair-accessible-vehicle-required"
AMBULATORY = "no-accessibility-requirement"


class InvalidPlacement(ValueError):
    """A policy returned a placement the harness did not offer it. A policy may
    only choose among CERTIFIED options; inventing one would bypass the authority
    that is the whole point of the package."""


class IrrevocabilityViolation(AssertionError):
    """A route changed under a request that had already been committed.

    Always a harness bug, and the one bug that would invalidate every number this
    module produces: the run would silently have become an offline re-plan while
    still being reported as an online one. Same failure the commingled harness
    guards against, checked the same way -- after every commitment, not assumed.
    """


# ==========================================================================
# Arrival order.
# ==========================================================================

def booking_order(instance: DarpInstance, *, seed: int) -> tuple[int, ...]:
    """The order in which the scheduler learns of the requests. ASSIGNED.

    The published instance files carry no booking times, so this is invented from
    a seed exactly as `commingled.derive_commingled_instance` invents booking
    leads. It matters more than it looks: arrival order is the one thing an
    operator does not control and cannot plan around, so a result from a SINGLE
    order is an anecdote. The benchmark sweeps seeds for that reason and the
    metrics carry the seed that produced them.
    """
    order = list(range(1, instance.num_requests + 1))
    Random(f"arrivals/{instance.name}/{seed}").shuffle(order)
    return tuple(order)


# ==========================================================================
# The plan.
# ==========================================================================

@dataclass(frozen=True)
class PoolingView:
    """Everything a placement policy is permitted to know at one decision point.

    The same discipline as `online.OnlineView`: the fleet as it stands, the
    request now arriving, the CERTIFIED options available to it, and the capacity
    estimate for each -- and nothing about arrivals that have not happened. There
    is no field for future requests and the harness never computes one, so a
    policy cannot be given foresight by accident.

    `options` are already certified. A policy chooses among them; it cannot invent
    one, and it cannot make one feasible by preferring it.
    """

    instance: DarpInstance
    profile: AccessibilityProfile
    request: int
    sequence: int
    routes: tuple[tuple[int, ...], ...]
    options: tuple[tuple[int, Certificate], ...]
    option_cost: tuple[float, ...]
    added_vehicle_miles: tuple[float, ...]
    capacity_cost: tuple[float | None, ...]
    accessible_capacity_cost: tuple[float | None, ...]
    trip_value: float
    capacity_weight: float
    accessible_weight: float


PlacementPolicy = Callable[[PoolingView], "tuple[int, Certificate] | None"]
"""Choose one of `view.options`, or None ONLY when there are none. Returning None
while certified options exist raises `RationingRefused` and the run produces no
result at all -- see the module docstring."""


@dataclass(frozen=True)
class Commitment:
    """One irrevocable placement decision, in the order it was made."""

    sequence: int
    request: int
    needs_wheelchair: bool
    vehicle: int | None
    options: int
    added_vehicle_miles: float | None
    capacity_cost: float | None
    accessible_capacity_cost: float | None
    pooled_with: tuple[int, ...]
    route_after: tuple[int, ...] | None = None
    """The chosen vehicle's route immediately after this commitment. Recorded so
    the whole run can be REPLAYED from the log and each decision re-examined
    against the fleet as it actually stood -- which is how the suite checks,
    independently of the harness's own bookkeeping, that no declined rider had a
    certified placement available. Without it the harness would be the only
    witness to its own most important claim."""

    @property
    def served(self) -> bool:
        return self.vehicle is not None

    def to_record(self) -> dict:
        return {
            "arrival": self.sequence,
            "request": self.request,
            "needs_wheelchair": self.needs_wheelchair,
            "vehicle": self.vehicle,
            "certified_options": self.options,
            "added_vehicle_miles": None if self.added_vehicle_miles is None else round(self.added_vehicle_miles, 6),
            "capacity_cost_trips_foreclosed": self.capacity_cost,
            "accessible_capacity_cost_trips_foreclosed": self.accessible_capacity_cost,
            "pooled_with": list(self.pooled_with),
            "route_after": None if self.route_after is None else list(self.route_after),
        }


@dataclass(frozen=True)
class PoolingPlan:
    """A finished plan plus the commitment log that produced it.

    `solution` is a `DarpSolution` in exactly the shape every other backend in
    this package returns, so the independent checkers judge it on identical terms
    and its status is honest: FEASIBLE, never optimal. An online run proves
    nothing about what was reachable, which is why the offline optimum is
    computed separately rather than inferred from this.
    """

    instance_name: str
    policy: str
    seed: int
    capacity_weight: float
    accessible_weight: float
    routes: tuple[tuple[int, ...], ...]
    schedules: tuple[tuple[float, ...], ...]
    commitments: tuple[Commitment, ...]
    solution: DarpSolution
    wall_time_s: float

    @property
    def served(self) -> tuple[int, ...]:
        return tuple(sorted(c.request for c in self.commitments if c.served))

    @property
    def unserved(self) -> tuple[int, ...]:
        return tuple(sorted(c.request for c in self.commitments if not c.served))

    def assignment(self) -> dict[int, int]:
        """request -> vehicle, for the requests that were served. The object two
        plans are diffed on when asking whether the decision actually changed."""
        return {c.request: c.vehicle for c in self.commitments if c.vehicle is not None}


def least_total_cost(view: PoolingView) -> tuple[int, Certificate] | None:
    """The shipped policy: cheapest certified placement once the future is priced.

    The harness computes

        cost(option) = added vehicle miles
                     + capacity_weight * trip_value
                       * (trips foreclosed + accessible_weight * accessible
                          trips foreclosed)

    and hands it over on the view, so the policy is a pure argmin and every term
    in it stays auditable on the commitment log. When `capacity_weight` is zero
    the cost collapses to added vehicle miles -- the rule
    `darp_solver._scan_insertions` already applies -- which is what makes the
    baseline a faithful stand-in for current practice rather than a strawman built
    to lose.

    Ties break on vehicle index, so the same instance and seed give the same plan.
    """
    if not view.options:
        return None
    best = min(
        range(len(view.options)),
        key=lambda i: (view.option_cost[i], view.options[i][0]),
    )
    return view.options[best]


def _solution_from(
    instance: DarpInstance,
    routes: Sequence[Sequence[int]],
    schedules: Sequence[Sequence[float]],
    served: Sequence[int],
) -> DarpSolution:
    return DarpSolution(
        instance_name=instance.name,
        num_requests=instance.num_requests,
        routes=tuple(
            DarpRoute(
                vehicle=v,
                visits=tuple(
                    DarpVisit(node_index=s, begin_service=schedules[v][k]) for k, s in enumerate(seq)
                ),
            )
            for v, seq in enumerate(routes)
        ),
        # FEASIBLE, never "optimal". A sequential run proves nothing about what
        # was achievable; that is the offline optimum's job.
        status="feasible" if len(served) == instance.num_requests else "incomplete",
        objective=sum(route_distance(instance, list(seq)) for seq in routes),
        served_requests=tuple(sorted(served)),
        solver_name=POOLING_PLANNER_NAME,
        solver_version=POOLING_PLANNER_VERSION,
        seed=0,
    )


def _depot_schedule(instance: DarpInstance) -> list[float]:
    t = instance.nodes[instance.depot_start].tw_start
    return [t, t]


def plan_online(
    instance: DarpInstance,
    profile: AccessibilityProfile,
    *,
    seed: int = 0,
    capacity_weight: float = 0.0,
    accessible_weight: float = 2.0,
    arrivals: Sequence[int] | None = None,
    draws: int = 3,
    scenarios: int = 8,
    policy_name: str | None = None,
    ensemble_every: int = 1,
    select: PlacementPolicy = least_total_cost,
) -> PoolingPlan:
    """Commit requests one at a time, irrevocably, choosing WHERE each one goes.

    The decision at each arrival:

        cost(option) = added vehicle miles
                     + capacity_weight * trip_value
                       * (trips foreclosed + accessible_weight * accessible
                          trips foreclosed)

    `trip_value` is the mean vehicle miles a request would need served ALONE, so
    `capacity_weight` is dimensionless: at 1.0, foreclosing one likely future trip
    is charged what serving one trip solo costs. Putting the two terms in the same
    unit is what stops the weight from being an arbitrary knob.

    THE PLANNER CANNOT DECLINE A SERVABLE RIDER. When certified options exist, one
    of them is committed. A request is recorded unserved only when the authority
    finds no certified insertion anywhere in the fleet -- that is an infeasibility
    verdict from two independent checkers, not a policy choice, and the harness
    raises `RationingRefused` if the two are ever confused.

    NO LOOKAHEAD. The scenario prior is refitted from the requests observed so far
    and nothing else; there is no parameter through which later arrivals could
    enter. `ensemble_every` re-fits every k arrivals, trading estimate freshness
    against planning time -- it never widens what the planner can see.

    `select` is pluggable so the two guards above are REACHABLE from a test. A
    policy that returns None while options exist raises `RationingRefused`; one
    that returns a placement the harness never offered raises `InvalidPlacement`.
    A guard nothing can reach is prose, and both are exercised by the conformance
    suite rather than argued for here.
    """
    t0 = time.perf_counter()
    order = tuple(arrivals) if arrivals is not None else booking_order(instance, seed=seed)
    if sorted(order) != list(range(1, instance.num_requests + 1)):
        raise ValueError("arrival order must be a permutation of the instance's requests")

    routes: list[list[int]] = empty_routes(instance)
    schedules: list[list[float]] = [_depot_schedule(instance) for _ in routes]
    trip_value = sum(
        route_distance(instance, solo_route(instance, r)) for r in range(1, instance.num_requests + 1)
    ) / instance.num_requests

    commitments: list[Commitment] = []
    served: list[int] = []
    observed: list[int] = []
    ensemble: CapacityEnsemble | None = None

    for k, request in enumerate(order):
        observed.append(request)
        frozen_prefix = [tuple(seq) for seq in routes]

        # --- what the authority allows -----------------------------------
        options: list[tuple[int, Certificate]] = []
        for v in range(instance.num_vehicles):
            outcome = certify_insertion(instance, profile, v, routes[v], request)
            if outcome.certificate is not None:
                options.append((v, outcome.certificate))

        if not options:
            commitments.append(
                Commitment(
                    sequence=k,
                    request=request,
                    needs_wheelchair=profile.needs_wheelchair(request),
                    vehicle=None,
                    options=0,
                    added_vehicle_miles=None,
                    capacity_cost=None,
                    accessible_capacity_cost=None,
                    pooled_with=(),
                )
            )
            continue

        # --- the capacity term, refitted on OBSERVED demand only ----------
        use_capacity = capacity_weight > 0.0 and len(observed) >= 2
        if use_capacity and (ensemble is None or k % max(1, ensemble_every) == 0):
            prior = prior_from_observed(instance, profile, observed)
            ensemble = build_ensemble(
                instance, profile, prior, draws=draws, scenarios=scenarios, seed=seed
            )

        # ONE snapshot per arrival, so every option is charged against the same
        # baseline and the same draws. Scenario noise then cancels between
        # options instead of deciding between them.
        snapshot = (
            ensemble.snapshot(routes) if (use_capacity and ensemble is not None) else None
        )

        added_miles: list[float] = []
        caps: list[float | None] = []
        accs: list[float | None] = []
        costs: list[float] = []
        for v, cert in options:
            added = route_distance(instance, list(cert.sequence)) - route_distance(instance, routes[v])
            added_miles.append(added)
            if snapshot is not None and ensemble is not None:
                value = ensemble.value_of_replacement(snapshot, v, cert.sequence)
                caps.append(value.trips_foreclosed)
                accs.append(value.accessible_trips_foreclosed)
                costs.append(
                    added
                    + capacity_weight
                    * trip_value
                    * (value.trips_foreclosed + accessible_weight * value.accessible_trips_foreclosed)
                )
            else:
                caps.append(None)
                accs.append(None)
                costs.append(added)

        view = PoolingView(
            instance=instance,
            profile=profile,
            request=request,
            sequence=k,
            routes=tuple(tuple(seq) for seq in routes),
            options=tuple(options),
            option_cost=tuple(costs),
            added_vehicle_miles=tuple(added_miles),
            capacity_cost=tuple(caps),
            accessible_capacity_cost=tuple(accs),
            trip_value=trip_value,
            capacity_weight=capacity_weight,
            accessible_weight=accessible_weight,
        )
        chosen = select(view)

        # PROPERTY, enforced rather than promised: this harness does not run a
        # policy that declines a rider it could serve. See the module docstring --
        # a run that could host one would produce numbers quotable in support of
        # trip-by-trip rationing, and none can be produced here.
        if chosen is None:
            raise RationingRefused(
                f"policy declined request {request} at arrival {k} although {len(options)} certified "
                f"placements existed. This harness does not run policies that decline riders they "
                f"could serve."
            )
        if chosen not in options:
            raise InvalidPlacement(
                f"policy returned a placement the harness did not offer for request {request}"
            )
        idx = options.index(chosen)
        v, cert = chosen
        added, cap, acc = added_miles[idx], caps[idx], accs[idx]
        pooled = tuple(r for r in cert.request_ids if r != request)
        routes[v] = list(cert.sequence)
        schedules[v] = list(cert.begin_service)
        served.append(request)
        commitments.append(
            Commitment(
                sequence=k,
                request=request,
                needs_wheelchair=profile.needs_wheelchair(request),
                vehicle=v,
                options=len(options),
                added_vehicle_miles=added,
                capacity_cost=None if cap is None else round(cap, 6),
                accessible_capacity_cost=None if acc is None else round(acc, 6),
                pooled_with=pooled,
                route_after=tuple(cert.sequence),
            )
        )

        # IRREVOCABILITY, checked rather than assumed: only the chosen vehicle's
        # route may have changed, and the requests already on it are all still on
        # it. A planner that quietly re-sequenced another vehicle would be an
        # offline re-planner wearing this harness's name.
        for other in range(instance.num_vehicles):
            if other == v:
                continue
            if tuple(routes[other]) != frozen_prefix[other]:
                raise IrrevocabilityViolation(
                    f"vehicle {other}'s route changed while committing request {request}"
                )
        before_ids = {instance.request_of(s) for s in frozen_prefix[v] if instance.is_pickup(s)}
        after_ids = {instance.request_of(s) for s in routes[v] if instance.is_pickup(s)}
        if not before_ids <= after_ids:
            raise IrrevocabilityViolation(
                f"committing request {request} dropped {sorted(before_ids - after_ids)} from vehicle {v}"
            )

    solution = _solution_from(instance, routes, schedules, served)
    # Self-audit against BOTH independent checkers before the plan is allowed out.
    violations = list(check_darp_feasibility(instance, solution)) + list(
        check_equipment_feasibility(instance, profile, solution)
    )
    if violations:
        raise AssertionError(f"the pooling planner produced an infeasible plan: {violations[:3]}")

    name = policy_name or (
        "cheapest-insertion" if capacity_weight == 0.0 else f"capacity-aware(w={capacity_weight})"
    )
    return PoolingPlan(
        instance_name=instance.name,
        policy=name,
        seed=seed,
        capacity_weight=capacity_weight,
        accessible_weight=accessible_weight,
        routes=tuple(tuple(seq) for seq in routes),
        schedules=tuple(tuple(s) for s in schedules),
        commitments=tuple(commitments),
        solution=solution,
        wall_time_s=round(time.perf_counter() - t0, 3),
    )


# ==========================================================================
# Evaluation. A better score that changes no assignment is worthless, so this
# measures the PLAN and not the objective.
# ==========================================================================

@dataclass(frozen=True)
class CohortService:
    """One accessibility cohort's service, in rider-level quantities.

    Occupancy and vehicle-miles-per-trip are FLEET ratios over shared vehicle
    miles; splitting them by rider needs an allocation rule, so this type reports
    the rider-level facts that need none (service rate, ride time, detour ratio,
    passenger miles) plus `allocated_vehicle_miles` under one stated rule: each
    arc's distance is divided equally among the people aboard it, and arcs with
    nobody aboard are deadhead and belong to no cohort. State the rule whenever
    the number is quoted; a different rule gives a different number and neither is
    more true than the other.
    """

    cohort: str
    demand: int
    served: int
    service_rate: float | None
    passenger_miles: float
    mean_ride_minutes: float | None
    mean_direct_minutes: float | None
    mean_detour_ratio: float | None
    allocated_vehicle_miles: float
    allocated_vehicle_miles_per_trip: float | None
    pooled_trips: int

    def to_record(self) -> dict:
        return {
            "cohort": self.cohort,
            "demand": self.demand,
            "served": self.served,
            "service_rate": None if self.service_rate is None else round(self.service_rate, 6),
            "passenger_miles": round(self.passenger_miles, 6),
            "mean_ride_minutes": None if self.mean_ride_minutes is None else round(self.mean_ride_minutes, 4),
            "mean_direct_minutes": None if self.mean_direct_minutes is None else round(self.mean_direct_minutes, 4),
            "mean_detour_ratio": None if self.mean_detour_ratio is None else round(self.mean_detour_ratio, 4),
            "allocated_vehicle_miles": round(self.allocated_vehicle_miles, 6),
            "allocated_vehicle_miles_per_trip": (
                None if self.allocated_vehicle_miles_per_trip is None
                else round(self.allocated_vehicle_miles_per_trip, 6)
            ),
            "pooled_trips": self.pooled_trips,
        }


@dataclass(frozen=True)
class PlanMetrics:
    """The decision-level evaluation. Read `trips_served` before `occupancy`.

    `feasibility_violations` MUST be zero. It is reported rather than asserted
    away because a metrics object that could not express an infeasible plan would
    be unable to report one, and a comparison against a baseline planner that does
    not know about equipment contention needs exactly that ability.
    """

    instance: str
    policy: str
    seed: int
    trips_demanded: int
    trips_served: int
    vehicle_miles: float
    passenger_miles: float
    occupancy: float
    vehicle_miles_per_served_trip: float | None
    shared_vehicle_miles: float
    shared_mileage_share: float
    deadhead_miles: float
    pooled_trips: int
    vehicles_used: int
    accessible_capacity_preserved: float | None
    total_capacity_preserved: float | None
    capacity_scenarios: int | None
    free_accessible_position_minutes: float
    accessible_position_minutes_available: float
    routing_violations: int
    equipment_violations: int
    cohorts: tuple[CohortService, ...]
    wall_time_s: float
    accessibility_note: str = ASSIGNED_ACCESSIBILITY_NOTE

    @property
    def feasibility_violations(self) -> int:
        return self.routing_violations + self.equipment_violations

    def cohort(self, name: str) -> CohortService:
        return next(c for c in self.cohorts if c.cohort == name)

    def headline(self) -> str:
        wc = self.cohort(WHEELCHAIR)
        amb = self.cohort(AMBULATORY)
        return (
            f"{self.instance}/{self.policy}: served {self.trips_served}/{self.trips_demanded} trips "
            f"({wc.served}/{wc.demand} needing an accessible vehicle, {amb.served}/{amb.demand} not); "
            f"occupancy {self.occupancy:.3f} pax-mi/veh-mi; {self.vehicle_miles_per_served_trip:.2f} "
            f"veh-mi per served trip; {self.feasibility_violations} feasibility violations. "
            f"Accessibility labels ASSIGNED, not observed."
            if self.vehicle_miles_per_served_trip is not None
            else f"{self.instance}/{self.policy}: served nothing."
        )

    def to_record(self) -> dict:
        return {
            "instance": self.instance,
            "policy": self.policy,
            "seed": self.seed,
            "trips_demanded": self.trips_demanded,
            "trips_served": self.trips_served,
            "vehicle_miles": round(self.vehicle_miles, 6),
            "passenger_miles": round(self.passenger_miles, 6),
            "occupancy_pax_miles_per_vehicle_mile": round(self.occupancy, 6),
            "vehicle_miles_per_served_trip": (
                None if self.vehicle_miles_per_served_trip is None
                else round(self.vehicle_miles_per_served_trip, 6)
            ),
            "shared_vehicle_miles": round(self.shared_vehicle_miles, 6),
            "shared_mileage_share": round(self.shared_mileage_share, 6),
            "deadhead_miles": round(self.deadhead_miles, 6),
            "pooled_trips": self.pooled_trips,
            "vehicles_used": self.vehicles_used,
            "accessible_capacity_preserved_scenario_trips": self.accessible_capacity_preserved,
            "total_capacity_preserved_scenario_trips": self.total_capacity_preserved,
            "capacity_scenarios_per_draw": self.capacity_scenarios,
            "free_accessible_position_minutes": round(self.free_accessible_position_minutes, 4),
            "accessible_position_minutes_available": round(self.accessible_position_minutes_available, 4),
            "routing_violations": self.routing_violations,
            "equipment_violations": self.equipment_violations,
            "feasibility_violations": self.feasibility_violations,
            "cohorts": [c.to_record() for c in self.cohorts],
            "wall_time_s": self.wall_time_s,
            "ACCESSIBILITY_LABELS": self.accessibility_note,
            "headline": self.headline(),
        }


def _per_rider(
    instance: DarpInstance, profile: AccessibilityProfile, sequence: Sequence[int]
) -> tuple[dict[int, float], dict[int, float], float]:
    """(allocated vehicle miles per rider, passenger miles per rider, deadhead).

    PASSENGER MILES need no allocation rule: a rider's passenger miles are the
    distance the vehicle covered while they were aboard, times how many people
    they are. They sum exactly to the route's passenger miles.

    VEHICLE MILES do need one, because a shared arc is driven once for several
    riders. The rule, applied everywhere and stated wherever the number is
    quoted: each arc's distance is divided among the PEOPLE aboard it, and arcs
    with nobody aboard are deadhead belonging to no rider. A different rule gives
    different per-cohort numbers and neither is more true -- what matters is that
    one rule is used for every plan being compared.
    """
    aboard = onboard_profile(instance, sequence)
    allocated: dict[int, float] = {}
    passenger: dict[int, float] = {}
    deadhead = 0.0
    live: list[int] = []
    for k, (a, b) in enumerate(zip(sequence, sequence[1:])):
        if instance.is_pickup(a):
            live.append(instance.request_of(a))
        elif instance.is_dropoff(a):
            live.remove(instance.request_of(a))
        d = instance.dist(a, b)
        heads = aboard[k]
        if heads <= 0 or not live:
            deadhead += d
            continue
        for r in live:
            seats = profile.riders(instance, r)
            allocated[r] = allocated.get(r, 0.0) + d * seats / heads
            passenger[r] = passenger.get(r, 0.0) + d * seats
    return allocated, passenger, deadhead


def free_accessible_minutes(
    instance: DarpInstance,
    profile: AccessibilityProfile,
    routes: Sequence[Sequence[int]],
    schedules: Sequence[Sequence[float]],
) -> tuple[float, float]:
    """(minutes an accessible vehicle could still board a wheelchair user,
    minutes available in total on accessible vehicles).

    The structural companion to the scenario-based `accessible_capacity_preserved`
    -- it needs no demand assumption at all, which is exactly why it is worth
    carrying next to a number that does. A vehicle counts as boardable in an
    interval when it has a free wheelchair position AND enough free floor to
    deploy a station. Measured over the depot window, because that is the shift
    the capacity is defined over; measuring only over a vehicle's active period
    would reward a plan for parking early.
    """
    depot = instance.nodes[instance.depot_start]
    close = instance.nodes[instance.depot_end].tw_end
    span = close - depot.tw_start
    available = span * len(profile.accessible_vehicles)
    free = 0.0
    for v, seq in enumerate(routes):
        if not profile.is_accessible(v):
            continue
        positions = profile.positions_on(v)
        events: list[tuple[float, int, int]] = []
        for k, node in enumerate(seq):
            if node in (instance.depot_start, instance.depot_end):
                continue
            r = instance.request_of(node)
            wc = 1 if profile.needs_wheelchair(r) else 0
            units = profile.floor_units(instance, r)
            sign = 1 if instance.is_pickup(node) else -1
            events.append((schedules[v][k], sign * wc, sign * units))
        events.sort()
        t = depot.tw_start
        wc_on = 0
        floor_on = 0
        for when, dwc, dfloor in events:
            if when > t:
                if wc_on < positions and (instance.vehicle_capacity - floor_on) >= profile.wheelchair_footprint:
                    free += min(when, close) - t
                t = min(when, close)
            wc_on += dwc
            floor_on += dfloor
        if t < close and wc_on < positions and (instance.vehicle_capacity - floor_on) >= profile.wheelchair_footprint:
            free += close - t
    return free, available


def evaluate_plan(
    instance: DarpInstance,
    profile: AccessibilityProfile,
    routes: Sequence[Sequence[int]],
    schedules: Sequence[Sequence[float]],
    *,
    policy: str,
    seed: int = 0,
    ensemble: CapacityEnsemble | None = None,
) -> PlanMetrics:
    """Judge a finished plan as a DECISION: who got served, at what occupancy, at
    what cost per trip, and how much accessible capacity it left behind.

    Works on any routed plan, whoever produced it -- this module's planner, the
    LNS heuristic, or CP-SAT -- so a comparison across planners is a comparison of
    plans and not of reporting conventions.
    """
    t0 = time.perf_counter()
    solution = _solution_from(
        instance, routes, schedules,
        sorted({instance.request_of(s) for seq in routes for s in seq if instance.is_pickup(s)}),
    )
    routing = check_darp_feasibility(instance, solution)
    equipment = check_equipment_feasibility(instance, profile, solution)

    served = sorted({instance.request_of(s) for seq in routes for s in seq if instance.is_pickup(s)})
    vm = sum(route_distance(instance, list(seq)) for seq in routes)
    pm = sum(route_passenger_miles(instance, profile, seq) for seq in routes)
    shared = sum(route_shared_vehicle_miles(instance, seq) for seq in routes)

    allocated: dict[int, float] = {}
    rider_pm: dict[int, float] = {}
    deadhead = 0.0
    pooled_requests: set[int] = set()
    for seq in routes:
        per, pmiles, dh = _per_rider(instance, profile, seq)
        for r, miles in per.items():
            allocated[r] = allocated.get(r, 0.0) + miles
        for r, miles in pmiles.items():
            rider_pm[r] = rider_pm.get(r, 0.0) + miles
        deadhead += dh
        aboard = onboard_profile(instance, seq)
        live: list[int] = []
        for k, node in enumerate(seq[:-1]):
            if instance.is_pickup(node):
                live.append(instance.request_of(node))
            elif instance.is_dropoff(node):
                live.remove(instance.request_of(node))
            if aboard[k] >= 2:
                pooled_requests.update(live)

    ride: dict[int, float] = {}
    for v, seq in enumerate(routes):
        at = {node: k for k, node in enumerate(seq)}
        for node in seq:
            if not instance.is_pickup(node):
                continue
            r = instance.request_of(node)
            d = instance.dropoff_index(r)
            ride[r] = schedules[v][at[d]] - (schedules[v][at[node]] + instance.nodes[node].service_duration)

    cohorts: list[CohortService] = []
    for name, wants in ((WHEELCHAIR, True), (AMBULATORY, False)):
        members = [r for r in range(1, instance.num_requests + 1) if profile.needs_wheelchair(r) is wants]
        got = [r for r in members if r in served]
        rides = [ride[r] for r in got if r in ride]
        directs = [instance.dist(instance.pickup_index(r), instance.dropoff_index(r)) for r in got]
        ratios = [
            ride[r] / instance.dist(instance.pickup_index(r), instance.dropoff_index(r))
            for r in got
            if r in ride and instance.dist(instance.pickup_index(r), instance.dropoff_index(r)) > 0
        ]
        alloc = sum(allocated.get(r, 0.0) for r in got)
        cohorts.append(
            CohortService(
                cohort=name,
                demand=len(members),
                served=len(got),
                service_rate=(len(got) / len(members)) if members else None,
                passenger_miles=sum(rider_pm.get(r, 0.0) for r in got),
                mean_ride_minutes=(sum(rides) / len(rides)) if rides else None,
                mean_direct_minutes=(sum(directs) / len(directs)) if directs else None,
                mean_detour_ratio=(sum(ratios) / len(ratios)) if ratios else None,
                allocated_vehicle_miles=alloc,
                allocated_vehicle_miles_per_trip=(alloc / len(got)) if got else None,
                pooled_trips=len([r for r in got if r in pooled_requests]),
            )
        )

    preserved_acc = preserved_all = None
    scenarios = None
    if ensemble is not None:
        total, acc = ensemble.residual(routes)
        preserved_all, preserved_acc = round(total, 4), round(acc, 4)
        scenarios = len(ensemble.lenses[0].scenarios)

    free, available = free_accessible_minutes(instance, profile, routes, schedules)
    used = sum(1 for seq in routes if any(not (s in (instance.depot_start, instance.depot_end)) for s in seq))

    return PlanMetrics(
        instance=instance.name,
        policy=policy,
        seed=seed,
        trips_demanded=instance.num_requests,
        trips_served=len(served),
        vehicle_miles=vm,
        passenger_miles=pm,
        occupancy=(pm / vm) if vm > 0 else 0.0,
        vehicle_miles_per_served_trip=(vm / len(served)) if served else None,
        shared_vehicle_miles=shared,
        shared_mileage_share=(shared / vm) if vm > 0 else 0.0,
        deadhead_miles=deadhead,
        pooled_trips=len(pooled_requests),
        vehicles_used=used,
        accessible_capacity_preserved=preserved_acc,
        total_capacity_preserved=preserved_all,
        capacity_scenarios=scenarios,
        free_accessible_position_minutes=free,
        accessible_position_minutes_available=available,
        routing_violations=len(routing),
        equipment_violations=len(equipment),
        cohorts=tuple(cohorts),
        wall_time_s=round(time.perf_counter() - t0, 4),
    )


def evaluate(
    instance: DarpInstance,
    profile: AccessibilityProfile,
    plan: PoolingPlan,
    *,
    ensemble: CapacityEnsemble | None = None,
) -> PlanMetrics:
    return evaluate_plan(
        instance, profile, plan.routes, plan.schedules,
        policy=plan.policy, seed=plan.seed, ensemble=ensemble,
    )


# ==========================================================================
# Did the decision actually change?
# ==========================================================================

@dataclass(frozen=True)
class PlanDiff:
    """How two plans differ AS DECISIONS.

    The packet's own standard: a better score that changes no assignment is
    worthless. `requests_moved` is therefore the first number to read, and
    `identical` is the honest verdict when a policy did nothing at all -- which is
    a result, and one this type is willing to state.
    """

    baseline: str
    candidate: str
    requests_moved: tuple[int, ...]
    requests_gained: tuple[int, ...]
    requests_lost: tuple[int, ...]
    pooling_changed: tuple[int, ...]
    occupancy_delta: float
    trips_served_delta: int
    accessible_trips_delta: int
    accessible_capacity_delta: float | None

    @property
    def identical(self) -> bool:
        return not (self.requests_moved or self.requests_gained or self.requests_lost or self.pooling_changed)

    def to_record(self) -> dict:
        return {
            "baseline": self.baseline,
            "candidate": self.candidate,
            "identical_decision": self.identical,
            "requests_moved_to_another_vehicle": list(self.requests_moved),
            "requests_gained": list(self.requests_gained),
            "requests_lost": list(self.requests_lost),
            "requests_with_different_pooling_partners": list(self.pooling_changed),
            "occupancy_delta": round(self.occupancy_delta, 6),
            "trips_served_delta": self.trips_served_delta,
            "accessible_trips_served_delta": self.accessible_trips_delta,
            "accessible_capacity_preserved_delta": self.accessible_capacity_delta,
        }


def _partners(instance: DarpInstance, routes: Sequence[Sequence[int]]) -> dict[int, frozenset[int]]:
    """For each served request, the set of riders aboard at the same time as them.
    Two plans can put every request on the same vehicle and still pool them
    differently; that difference is invisible to a vehicle-level diff and is
    exactly what this packet changes."""
    out: dict[int, set[int]] = {}
    for seq in routes:
        live: list[int] = []
        for node in seq:
            if instance.is_pickup(node):
                r = instance.request_of(node)
                for other in live:
                    out.setdefault(r, set()).add(other)
                    out.setdefault(other, set()).add(r)
                out.setdefault(r, set())
                live.append(r)
            elif instance.is_dropoff(node):
                live.remove(instance.request_of(node))
    return {r: frozenset(v) for r, v in out.items()}


def diff_plans(
    instance: DarpInstance,
    profile: AccessibilityProfile,
    baseline: PlanMetrics,
    baseline_routes: Sequence[Sequence[int]],
    candidate: PlanMetrics,
    candidate_routes: Sequence[Sequence[int]],
) -> PlanDiff:
    """Compare two plans as decisions, not as objective values."""
    def assign(routes: Sequence[Sequence[int]]) -> dict[int, int]:
        return {
            instance.request_of(s): v
            for v, seq in enumerate(routes)
            for s in seq
            if instance.is_pickup(s)
        }

    a, b = assign(baseline_routes), assign(candidate_routes)
    moved = tuple(sorted(r for r in set(a) & set(b) if a[r] != b[r]))
    gained = tuple(sorted(set(b) - set(a)))
    lost = tuple(sorted(set(a) - set(b)))
    pa, pb = _partners(instance, baseline_routes), _partners(instance, candidate_routes)
    pooling_changed = tuple(
        sorted(r for r in set(pa) & set(pb) if pa[r] != pb[r])
    )
    acc_delta = None
    if baseline.accessible_capacity_preserved is not None and candidate.accessible_capacity_preserved is not None:
        acc_delta = round(
            candidate.accessible_capacity_preserved - baseline.accessible_capacity_preserved, 4
        )
    return PlanDiff(
        baseline=baseline.policy,
        candidate=candidate.policy,
        requests_moved=moved,
        requests_gained=gained,
        requests_lost=lost,
        pooling_changed=pooling_changed,
        occupancy_delta=candidate.occupancy - baseline.occupancy,
        trips_served_delta=candidate.trips_served - baseline.trips_served,
        accessible_trips_delta=(
            candidate.cohort(WHEELCHAIR).served - baseline.cohort(WHEELCHAIR).served
        ),
        accessible_capacity_delta=acc_delta,
    )


def routes_from_solution(instance: DarpInstance, solution: DarpSolution) -> tuple[list[list[int]], list[list[float]]]:
    """Project any `DarpSolution` onto the (routes, schedules) pair this module's
    evaluation works on, so a plan from the LNS heuristic or from CP-SAT is judged
    by exactly the same metric code."""
    routes: list[list[int]] = []
    schedules: list[list[float]] = []
    by_vehicle = {r.vehicle: r for r in solution.routes}
    for v in range(instance.num_vehicles):
        route = by_vehicle.get(v)
        if route is None:
            routes.append([instance.depot_start, instance.depot_end])
            schedules.append(_depot_schedule(instance))
            continue
        routes.append([visit.node_index for visit in route.visits])
        schedules.append([visit.begin_service for visit in route.visits])
    return routes, schedules
