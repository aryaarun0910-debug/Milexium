"""Commingled demand-response: the shared floor the v0.1 IR cannot express.

WHAT COMMINGLING IS. A commingled service carries general-public riders and
riders who need a wheelchair-accessible vehicle on the SAME fleet, in the same
vehicles, at the same time. The interesting question about it is whether a
general-public trip accepted at nine in the morning quietly costs a wheelchair
user a trip at four in the afternoon.

WHY THIS MODULE HAS TO EXIST. `metis.decide.feasibility` checks the two
capacity pools INDEPENDENTLY: a request with `needs_wheelchair` consumes one of
`capacity_wheelchair`, an ambulatory party consumes `party_size` of
`capacity_ambulatory`, and neither ever touches the other. That is a faithful
model of exactly one vehicle configuration -- a bus with a permanently reserved,
never-reclaimed wheelchair bay. Under that model commingling is FREE: an
ambulatory rider can never displace a wheelchair user, so the exposure question
this package exists to measure is vacuous by construction.

It is also not how the fleet works. In a cutaway van or a minivan a wheelchair
station is MADE by folding up a bench; the seats and the station are drawn from
one floor. So this module adds one constraint the IR does not carry:

    for every vehicle, at every instant:
        sum(party_size of ambulatory riders onboard)
      + wheelchair_footprint * (wheelchair riders onboard)
      <= floor_units(vehicle)

That single constraint is what makes an ambulatory commitment able to consume
capacity a later wheelchair user needed. Everything downstream -- the online
harness, the capacity attribution, the accessibility breakdown -- is measuring
the consequences of it. If a reader rejects the constraint they are asserting
that no vehicle in the fleet ever converts a wheelchair station into seats, and
the honest answer is that they should then expect an exposure of zero.

`metis.decide.ir` and `metis.decide.feasibility` are NOT modified. The
floor is an ADDITIVE constraint layered on top of them: every solution produced
here passes the original independent checker first, and the floor checker second.

TWO IMPLEMENTATIONS OF THE FLOOR, DELIBERATELY. `_floor_fits` (incremental,
used by the generators to prune) and `check_floor_feasibility` (a sweep over a
finished solution, used as the arbiter) are written separately and neither calls
the other. That mirrors the existing `solver._fits_capacity` /
`feasibility._capacity_violations` split: a generator that graded its own
homework would not be a check.

THE OFFLINE OPTIMUM. `solve_commingled_offline` is a CP-SAT model of the whole
instance seen at once -- every request known before any decision is made. It is
the yardstick the online harness is measured against, and it is deliberately a
near-copy of `metis.decide.cpsat`'s model plus the floor cumulative, sharing
`solver._candidate_times` with every other backend in the package so that a gap
between online and offline measures FORESIGHT and not a difference of grid.

Its honesty contract is the package's: `OPTIMAL` only on a real proof, and the
proof is optimality RELATIVE TO THE POLICY'S PICKUP-TIME GRID -- the same bounded
claim `solver._solve_exact` makes and the same shape as ADR-0060's "optimal
within the lattice resolution". Never absolutely.

FRAMING. Nothing in this module, or anything built on it, is a reason to serve
fewer riders. Restricting transit use is not the objective. The floor constraint
describes a vehicle, not a policy; the measurement it enables exists to show
whether a commingling policy is quietly shifting cost onto disabled riders, so
that capacity can be RELEASED to them -- never to justify rationing trips.
"""

from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping, Sequence

from themis.canonical.ids import PolicyId, RequestId, TenantId, VehicleId
from themis.canonical.vocab import ReasonCode, ScheduleRunStatus
from metis.decide.capability import SolverUnavailable, ortools_capability
from metis.decide.feasibility import Violation, check_feasibility
from metis.decide.ir import (
    Assignment,
    DecisionPolicy,
    DecisionProblem,
    DecisionSolution,
    DecisionVehicle,
    Denial,
    RideRequest,
)
# Shared on purpose with every other backend in the package: if this module built
# its own pickup-time grid, an online-vs-offline gap could be a discretization
# artefact and the headline number would be meaningless. See the module docstring.
from metis.decide.solver import _candidate_times, _fits_capacity, _static_reasons

COMMINGLED_SOLVER_NAME = "milexium-decide-commingled-offline"
COMMINGLED_SOLVER_VERSION = "0.4.0"

_US_PER_MINUTE = 60_000_000
_OBJ_SCALE = 1000
_MAX_SCALED_OBJECTIVE = 2**62

_DEFAULT_WHEELCHAIR_FOOTPRINT = 2
"""Seat-equivalents a deployed wheelchair station occupies. Two is the common
cutaway/minivan case (a station replaces a two-seat bench). It is a PARAMETER,
not a constant, because it is a claim about a vehicle: a fleet whose stations sit
in dedicated floor space has a footprint of 0 against the ambulatory seats, and
under that value this whole measurement correctly reports no exposure."""


class DenialPenaltyTooWeak(ValueError):
    """The policy's `unserved_penalty` does not dominate the ride-time term.

    Raised rather than silently measured around. This package reports a shortfall
    in TRIPS, which is only a well-defined optimum when denying a trip is always
    worse than serving it -- otherwise the "optimum" can legitimately prefer to
    serve fewer, shorter trips and a trip-count gap stops meaning anything. The
    exposure measurement would still produce a number; it would just not be the
    number it claims to be.
    """


# ==========================================================================
# The fleet: floor space per vehicle.
# ==========================================================================

@dataclass(frozen=True)
class CommingledFleet:
    """Floor space per vehicle, in seat-equivalents, plus what a wheelchair
    station costs against it.

    `floor_units` is a tuple of (vehicle_id, units) pairs rather than a dict so
    the spec is hashable and printable in a report -- an exposure number that
    cannot be traced back to the fleet assumption that produced it is not
    evidence of anything.
    """

    floor_units: tuple[tuple[str, int], ...]
    wheelchair_footprint: int = _DEFAULT_WHEELCHAIR_FOOTPRINT

    def units(self, vehicle_id: str) -> int:
        for vid, units in self.floor_units:
            if vid == str(vehicle_id):
                return units
        raise KeyError(f"no floor spec for vehicle {vehicle_id}")

    def demand(self, request: RideRequest) -> int:
        """Floor units this request occupies while onboard."""
        return self.wheelchair_footprint if request.needs_wheelchair else request.party_size

    def binds_anywhere(self, problem: DecisionProblem) -> bool:
        """True iff the floor is capable of forbidding something the two IR pools
        would allow -- i.e. some vehicle's full pool-legal load exceeds its floor.

        Exists so a test suite can REFUSE to draw conclusions from instances where
        the constraint under study is slack. An instance where this is False makes
        every commingling assertion vacuous, which is precisely the shape of
        failure this repository has shipped before.
        """
        for veh in problem.vehicles:
            pool_max = veh.capacity_ambulatory + veh.capacity_wheelchair * self.wheelchair_footprint
            if pool_max > self.units(str(veh.vehicle_id)):
                return True
        return False

    @classmethod
    def from_problem(
        cls,
        problem: DecisionProblem,
        *,
        wheelchair_footprint: int = _DEFAULT_WHEELCHAIR_FOOTPRINT,
        units: Mapping[str, int] | None = None,
    ) -> "CommingledFleet":
        """Default floor: a vehicle's ambulatory seat count IS its floor, widened
        where necessary so its own declared wheelchair positions still fit.

        The widening matters: a wheelchair-only van (`capacity_ambulatory=0`,
        `capacity_wheelchair=1`) would otherwise be given a floor of zero and
        could carry nobody, turning a modelling default into a fake denial.
        """
        pairs = []
        for veh in problem.vehicles:
            vid = str(veh.vehicle_id)
            if units is not None and vid in units:
                pairs.append((vid, int(units[vid])))
                continue
            pairs.append((vid, max(veh.capacity_ambulatory, veh.capacity_wheelchair * wheelchair_footprint)))
        return cls(floor_units=tuple(pairs), wheelchair_footprint=wheelchair_footprint)


# ==========================================================================
# Placements: the one definition of "can this ride go here", shared by the
# online harness and by every counterfactual asked about it.
# ==========================================================================

@dataclass(frozen=True)
class Placement:
    """A concrete (vehicle, pickup, dropoff) a request could be committed to."""

    vehicle_id: str
    pickup_time: datetime
    dropoff_time: datetime


@dataclass(frozen=True)
class AcceptedRide:
    """A ride already committed to. Frozen: an accepted ride is not editable, and
    the online harness depends on that being true at the type level rather than
    by convention."""

    request_id: str
    placement: Placement
    needs_wheelchair: bool
    party_size: int


def _placed_tuples(accepted: Iterable[AcceptedRide], vehicle_id: str) -> list[tuple]:
    """The `(pickup, dropoff, is_wheelchair, load)` shape `solver._fits_capacity`
    expects, for one vehicle."""
    return [
        (a.placement.pickup_time, a.placement.dropoff_time, a.needs_wheelchair,
         1 if a.needs_wheelchair else a.party_size)
        for a in accepted
        if a.placement.vehicle_id == vehicle_id
    ]


def _floor_fits(
    fleet: CommingledFleet,
    accepted: Iterable[AcceptedRide],
    vehicle_id: str,
    demand: int,
    pickup: datetime,
    dropoff: datetime,
) -> bool:
    """Would adding [pickup, dropoff) at `demand` floor units keep this vehicle
    inside its floor? Boundary convention matches the IR checker's sweep: a
    drop-off frees the floor at the instant the next pickup takes it."""
    capacity = fleet.units(vehicle_id)
    if demand > capacity:
        return False
    events: list[tuple[datetime, int]] = [(pickup, demand), (dropoff, -demand)]
    for a in accepted:
        if a.placement.vehicle_id != vehicle_id:
            continue
        d = fleet.wheelchair_footprint if a.needs_wheelchair else a.party_size
        events.append((a.placement.pickup_time, d))
        events.append((a.placement.dropoff_time, -d))
    events.sort(key=lambda e: (e[0], e[1]))  # -d before +d at equal instants
    onboard = 0
    for _t, delta in events:
        onboard += delta
        if onboard > capacity:
            return False
    return True


def feasible_placements(
    problem: DecisionProblem,
    fleet: CommingledFleet,
    accepted: Sequence[AcceptedRide],
    request: RideRequest,
) -> tuple[Placement, ...]:
    """Every (vehicle, pickup) this request could take RIGHT NOW, given the rides
    already committed to. Deterministic order: vehicle id, then pickup instant.

    Candidate pickup instants come from `solver._candidate_times`, the same grid
    the exact backend, the CP-SAT backend and the offline optimum all search. Two
    gates then apply: the IR's own per-pool capacity (`solver._fits_capacity`,
    untouched) and this module's floor.
    """
    out: list[Placement] = []
    demand = fleet.demand(request)
    for veh in sorted(problem.vehicles, key=lambda v: str(v.vehicle_id)):
        vid = str(veh.vehicle_id)
        placed = _placed_tuples(accepted, vid)
        for pickup in _candidate_times(request, veh, problem.policy.time_granularity_minutes):
            dropoff = pickup + request.nominal_ride
            if not _fits_capacity(placed, veh, request, pickup, dropoff):
                continue
            if not _floor_fits(fleet, accepted, vid, demand, pickup, dropoff):
                continue
            out.append(Placement(vehicle_id=vid, pickup_time=pickup, dropoff_time=dropoff))
    return tuple(out)


def has_placement(
    problem: DecisionProblem,
    fleet: CommingledFleet,
    accepted: Sequence[AcceptedRide],
    request: RideRequest,
) -> bool:
    """Short-circuiting `bool(feasible_placements(...))`.

    Separate because the capacity attribution asks this question thousands of
    times over subsets of the committed set, and building every placement each
    time is the difference between a benchmark that runs and one that does not.
    It must agree with `feasible_placements` exactly; the conformance suite pins
    that rather than assuming it.
    """
    demand = fleet.demand(request)
    for veh in sorted(problem.vehicles, key=lambda v: str(v.vehicle_id)):
        vid = str(veh.vehicle_id)
        placed = _placed_tuples(accepted, vid)
        for pickup in _candidate_times(request, veh, problem.policy.time_granularity_minutes):
            dropoff = pickup + request.nominal_ride
            if not _fits_capacity(placed, veh, request, pickup, dropoff):
                continue
            if _floor_fits(fleet, accepted, vid, demand, pickup, dropoff):
                return True
    return False


# ==========================================================================
# The floor checker: an arbiter, written separately from the pruning above.
# ==========================================================================

def check_floor_feasibility(
    problem: DecisionProblem,
    fleet: CommingledFleet,
    solution: DecisionSolution,
) -> list[Violation]:
    """Every floor violation in `solution`, re-derived from the assignments.

    Independent of `_floor_fits` by construction -- this sweeps a finished plan;
    that one answers an insertion question -- and independent of every solver in
    the package. It will reject an over-loaded plan whoever wrote it.

    This is a SUPPLEMENT to `feasibility.check_feasibility`, never a replacement:
    a commingled solution must pass both, and callers here always run both.
    """
    by_request = {str(r.request_id): r for r in problem.requests}
    violations: list[Violation] = []
    by_vehicle: dict[str, list[Assignment]] = {}
    for a in solution.assignments:
        by_vehicle.setdefault(str(a.vehicle_id), []).append(a)

    for vid, assigns in by_vehicle.items():
        capacity = fleet.units(vid)
        events: list[tuple[datetime, int, int, str]] = []
        for a in assigns:
            req = by_request[str(a.request_id)]
            demand = fleet.wheelchair_footprint if req.needs_wheelchair else req.party_size
            events.append((a.pickup_time, 1, demand, str(a.request_id)))
            events.append((a.dropoff_time, 0, -demand, str(a.request_id)))
        events.sort(key=lambda e: (e[0], e[1]))
        onboard = 0
        for _t, _kind, delta, rid in events:
            onboard += delta
            if onboard > capacity:
                violations.append(
                    Violation(
                        ReasonCode.NO_ACCESSIBLE_CAPACITY,
                        f"commingled floor load {onboard} exceeds {capacity} seat-equivalents on "
                        f"vehicle {vid} (wheelchair station footprint {fleet.wheelchair_footprint})",
                        rid,
                        vid,
                    )
                )
    return violations


def check_commingled(
    problem: DecisionProblem,
    fleet: CommingledFleet,
    solution: DecisionSolution,
) -> list[Violation]:
    """Both gates: the original IR checker, then the floor. Nothing in this
    package reports a commingled solution that has not been through this."""
    return check_feasibility(problem, solution) + check_floor_feasibility(problem, fleet, solution)


# ==========================================================================
# Objective: shortfall in TRIPS, tie-broken on in-vehicle minutes.
# ==========================================================================

def assert_denial_dominates(problem: DecisionProblem) -> None:
    """Refuse to measure a trip-count shortfall against an objective that might
    rationally prefer to serve fewer trips.

    The exposure report's headline is "the online run served N fewer trips than
    the offline optimum". That is only the optimum's own preference if denying
    any single request costs more than serving EVERY request could. Checked here,
    once, loudly -- a silently mis-weighted policy would produce a plausible
    number that answers a different question.
    """
    policy = problem.policy
    worst_serve_cost = sum(
        policy.ride_time_weight * r.nominal_ride_time_minutes for r in problem.requests
    )
    for req in problem.requests:
        penalty = policy.unserved_penalty
        if req.must_serve:
            continue  # a mandate is handled by the IR's own INFEASIBLE verdict
        if penalty <= worst_serve_cost:
            raise DenialPenaltyTooWeak(
                f"unserved_penalty {penalty} does not dominate the total ride-time cost "
                f"{worst_serve_cost}; a trip-count shortfall against this objective would not "
                f"be the optimum's own preference"
            )


def commingled_objective(problem: DecisionProblem, served_ids: Iterable[str]) -> float:
    """The objective this package minimises, recomputed from a served set.
    Used to cross-check a solver's self-reported number, never to replace it."""
    served = set(served_ids)
    total = 0.0
    for req in problem.requests:
        if str(req.request_id) in served:
            total += problem.policy.ride_time_weight * req.nominal_ride_time_minutes
        else:
            total += problem.policy.unserved_penalty
    return total


# ==========================================================================
# The offline optimum: every request visible before any decision is made.
# ==========================================================================

@dataclass(frozen=True)
class CommingledOutcome:
    """An offline solve of a commingled instance.

    `proven_optimal` means CP-SAT closed the model, and the model is the instance
    discretized onto the policy's pickup-time grid. So the claim is "optimal
    relative to that grid", exactly as `solver._solve_exact` claims and exactly as
    ADR-0060's `certified_optimal` means "within the lattice resolution". Neither
    is an absolute optimality claim and this one must not be quoted as one.

    `pool_only_bound` is the objective of the SAME instance with the floor
    constraint dropped -- a relaxation, so a rigorous lower bound on this
    objective, computed by a completely separate model (`metis.decide.cpsat`,
    unmodified). It is carried because a bound from an independent model is the
    only cheap evidence that this one is not quietly wrong.
    """

    solution: DecisionSolution
    served_ids: tuple[str, ...]
    objective: float | None
    proven_optimal: bool
    raw_status: str
    wall_time_s: float
    deterministic_time: float
    pool_only_bound: float | None = None
    pool_only_served: int | None = None

    @property
    def served(self) -> int:
        return len(self.served_ids)


def solve_commingled_offline(
    problem: DecisionProblem,
    fleet: CommingledFleet,
    *,
    seed: int = 0,
    max_deterministic_time: float | None = 60.0,
    max_time_s: float | None = None,
    workers: int = 1,
) -> CommingledOutcome:
    """Solve the whole instance at once: the yardstick the online run is measured
    against.

    Determinism, same contract as the rest of Program F: `workers=1` plus a
    deterministic-time budget and no wall-clock cap makes the answer reproducible
    across machines. `max_time_s` is a safety valve and gives that up.
    """
    cap = ortools_capability()
    if not cap.available:
        raise SolverUnavailable(f"the commingled offline optimum requires OR-Tools: {cap.detail}")
    from ortools.sat.python import cp_model

    assert_denial_dominates(problem)

    policy = problem.policy
    requests = sorted(problem.requests, key=lambda r: (r.pickup_window_start, str(r.request_id)))
    vehicles = sorted(problem.vehicles, key=lambda v: str(v.vehicle_id))
    origin = min([v.shift_start for v in problem.vehicles] + [r.pickup_window_start for r in problem.requests])

    def us(t: datetime) -> int:
        return round((t - origin).total_seconds() * 1_000_000)

    model = cp_model.CpModel()
    x: dict[tuple[int, int], object] = {}
    starts: dict[tuple[int, int], object] = {}
    # (interval, pool demand, floor demand, is_wheelchair) per vehicle
    per_vehicle: dict[int, list[tuple[object, int, int, bool]]] = {vi: [] for vi in range(len(vehicles))}

    for ri, req in enumerate(requests):
        ride_us = round(req.nominal_ride_time_minutes * _US_PER_MINUTE)
        served_lits = []
        for vi, veh in enumerate(vehicles):
            candidates = _candidate_times(req, veh, policy.time_granularity_minutes)
            if not candidates:
                continue
            lit = model.NewBoolVar(f"x_r{ri}_v{vi}")
            domain = cp_model.Domain.FromValues(sorted({us(c) for c in candidates}))
            st = model.NewIntVarFromDomain(domain, f"start_r{ri}_v{vi}")
            iv = model.NewOptionalIntervalVar(st, ride_us, st + ride_us, lit, f"iv_r{ri}_v{vi}")
            x[(ri, vi)] = lit
            starts[(ri, vi)] = st
            pool_demand = 1 if req.needs_wheelchair else req.party_size
            per_vehicle[vi].append((iv, pool_demand, fleet.demand(req), req.needs_wheelchair))
            served_lits.append(lit)
        if served_lits:
            model.AddAtMostOne(served_lits)

    for vi, veh in enumerate(vehicles):
        # The IR's own two pools, modelled exactly as metis.decide.cpsat does.
        for wheelchair, capacity in ((True, veh.capacity_wheelchair), (False, veh.capacity_ambulatory)):
            ivs = [(iv, pool) for iv, pool, _floor, is_wc in per_vehicle[vi] if is_wc is wheelchair]
            if ivs:
                model.AddCumulative([iv for iv, _ in ivs], [d for _, d in ivs], capacity)
        # THE COMMINGLING CONSTRAINT: one floor, both cohorts. This is the whole
        # difference between this model and the pool-only one, and it is the only
        # reason an ambulatory commitment can cost a wheelchair user a trip.
        allv = per_vehicle[vi]
        if allv:
            model.AddCumulative(
                [iv for iv, _p, _f, _w in allv],
                [f for _iv, _p, f, _w in allv],
                fleet.units(str(veh.vehicle_id)),
            )

    constant = 0
    terms = []
    for ri, req in enumerate(requests):
        penalty = policy.unserved_penalty
        scaled_penalty = round(penalty * _OBJ_SCALE)
        scaled_serve = round(policy.ride_time_weight * req.nominal_ride_time_minutes * _OBJ_SCALE)
        constant += scaled_penalty
        delta = scaled_serve - scaled_penalty
        for vi in range(len(vehicles)):
            lit = x.get((ri, vi))
            if lit is not None:
                terms.append(delta * lit)
    if constant >= _MAX_SCALED_OBJECTIVE:
        raise ValueError(f"scaled objective bound {constant} exceeds the safe integer range")
    model.Minimize(sum(terms) + constant)

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

    has_solution = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    proven = status == cp_model.OPTIMAL

    assign: list[tuple[int, int, datetime, datetime]] = []
    if has_solution:
        for (ri, vi), lit in x.items():
            if solver.BooleanValue(lit):
                req = requests[ri]
                pickup = origin + timedelta(microseconds=int(solver.Value(starts[(ri, vi)])))
                assign.append((ri, vi, pickup, pickup + req.nominal_ride))

    served_ids = tuple(sorted(str(requests[ri].request_id) for ri, _v, _p, _d in assign))
    objective = round(solver.ObjectiveValue()) / _OBJ_SCALE if has_solution else None

    assignments = tuple(
        Assignment(
            request_id=requests[ri].request_id,
            vehicle_id=vehicles[vi].vehicle_id,
            pickup_time=pt,
            dropoff_time=dt,
        )
        for ri, vi, pt, dt in sorted(assign, key=lambda a: str(requests[a[0]].request_id))
    )
    unserved = tuple(
        Denial(
            request_id=r.request_id,
            reason_codes=_static_reasons(r, problem) if proven else (ReasonCode.SOLVER_TIMEOUT,),
        )
        for r in problem.requests
        if str(r.request_id) not in set(served_ids)
    )
    # OPTIMAL only on a proof; a cut-off search is TIMEOUT with no bound and no
    # gap on the DecisionSolution, whose contract this module does not weaken.
    solution = DecisionSolution(
        status=ScheduleRunStatus.OPTIMAL if proven else ScheduleRunStatus.TIMEOUT,
        assignments=assignments,
        unserved=unserved,
        objective_value=objective,
        bound=objective if proven else None,
        gap=0.0 if proven else None,
        seed=seed,
        solver_name=COMMINGLED_SOLVER_NAME,
        solver_version=COMMINGLED_SOLVER_VERSION,
    )
    # Self-audit against BOTH independent checkers before this is allowed out.
    violations = check_commingled(problem, fleet, solution)
    if violations:
        raise AssertionError(f"the commingled offline model produced an infeasible plan: {violations[:3]}")

    return CommingledOutcome(
        solution=solution,
        served_ids=served_ids,
        objective=objective,
        proven_optimal=proven,
        raw_status=status_name,
        wall_time_s=round(wall, 4),
        deterministic_time=round(solver.deterministic_time, 4),
    )


def pool_only_relaxation(
    problem: DecisionProblem,
    *,
    seed: int = 0,
    max_deterministic_time: float | None = 60.0,
) -> tuple[float | None, int | None, bool]:
    """Solve the SAME instance with the floor constraint dropped, using the
    unmodified `metis.decide.cpsat` backend that landed with ADR-0060.

    Dropping a constraint is a relaxation, so on this minimisation its optimum is
    a rigorous LOWER BOUND on the commingled optimum, and its served count is an
    upper bound on the commingled served count. Two independent models that must
    stand in a known relation is the cheapest correctness evidence available, and
    the conformance suite asserts the relation rather than assuming it.

    Returns (objective, served_count, proven). `proven` False means the returned
    numbers are an incumbent, not a bound, and callers must not use them as one.
    """
    from metis.decide.cpsat import solve_cpsat_detailed

    outcome = solve_cpsat_detailed(
        problem, seed=seed, max_deterministic_time=max_deterministic_time
    )
    proven = outcome.solution.status is ScheduleRunStatus.OPTIMAL
    served = len(outcome.solution.assignments)
    return outcome.objective, served, proven


# ==========================================================================
# Building a commingled instance.
#
# READ THIS BEFORE CITING ANY NUMBER PRODUCED FROM THESE INSTANCES.
#
# The published dial-a-ride benchmark files carry real, non-trivial temporal
# structure -- 15-minute windows, ride-time ceilings, a fleet, a shift -- and
# that structure is used here unchanged. They carry NO accessibility attribute,
# because the literature they come from does not model one. So the wheelchair
# labels, the booking lead times, and the floor spec are ASSIGNED BY THIS
# FUNCTION from a seed. They are modelling assumptions, not measurements.
#
# The consequence, stated plainly: results from these instances demonstrate that
# the measurement WORKS and that it DISCRIMINATES between cohorts. They say
# nothing whatsoever about the exposure any real agency's riders actually face.
# ==========================================================================

@dataclass(frozen=True)
class InstanceProvenance:
    """Where every field of a generated instance came from. Carried into the
    report so no reader has to take the honesty of the labels on trust."""

    source: str
    timing_from: str
    accessibility_labels: str
    fleet_sizing: str
    booking_times: str
    fleet_floor: str
    wheelchair_share: float
    seed: int

    def to_record(self) -> dict:
        return {
            "source_instance": self.source,
            "REAL_timing_from": self.timing_from,
            "ASSIGNED_accessibility_labels": self.accessibility_labels,
            "ASSIGNED_fleet_sizing": self.fleet_sizing,
            "ASSIGNED_booking_times": self.booking_times,
            "ASSIGNED_fleet_floor": self.fleet_floor,
            "wheelchair_share": self.wheelchair_share,
            "seed": self.seed,
        }


def _seeded_id(kind, rng: random.Random):
    """A deterministic UUIDv7-shaped id.

    The canonical id types validate the version nibble, so a run has to mint real
    v7 values; `uuid.uuid7()` is time-based and would make every generated
    instance a different instance. A seeded RNG with the version/variant bits set
    correctly gives reproducible instances, which is the whole basis for
    re-running an exposure measurement and getting the same number.
    """
    raw = bytearray(rng.getrandbits(8) for _ in range(16))
    raw[6] = (raw[6] & 0x0F) | 0x70   # version 7
    raw[8] = (raw[8] & 0x3F) | 0x80   # RFC 9562 variant
    return kind(str(uuid.UUID(bytes=bytes(raw))))


@dataclass(frozen=True)
class CommingledInstance:
    """A commingled instance plus the arrival order and the provenance of every
    assumption baked into it. The three travel together on purpose: an exposure
    number separated from its labelling assumption is not interpretable."""

    problem: DecisionProblem
    fleet: CommingledFleet
    booked_at: tuple[tuple[str, datetime], ...]
    provenance: InstanceProvenance

    def arrival_order(self) -> tuple[RideRequest, ...]:
        """Requests in the order the scheduler learned of them. Ties broken by
        request id so the order is total and reproducible."""
        booking = dict(self.booked_at)
        return tuple(
            sorted(self.problem.requests, key=lambda r: (booking[str(r.request_id)], str(r.request_id)))
        )


def derive_commingled_instance(
    darp_instance,
    *,
    seed: int,
    wheelchair_share: float = 0.35,
    num_vehicles: int | None = None,
    vehicle_capacity: int | None = None,
    accessible_vehicles: int | None = None,
    wheelchair_footprint: int = _DEFAULT_WHEELCHAIR_FOOTPRINT,
    time_granularity_minutes: int = 5,
    min_lead_minutes: int = 15,
    max_lead_minutes: int = 90,
) -> CommingledInstance:
    """Turn a published Cordeau dial-a-ride instance into a commingled same-day
    instance, recording exactly which parts are real and which are assigned.

    REAL, taken from the instance file unchanged: the number of requests, the
    number of vehicles, the depot/shift window, the 15-minute service windows,
    the maximum ride time, the vehicle capacity, and each request's direct
    pickup-to-drop-off travel time (used as its nominal in-vehicle duration).

    ASSIGNED HERE from `seed`, and therefore NOT evidence about anyone: which
    riders need a wheelchair-accessible vehicle, which vehicles are accessible,
    how far ahead each request was booked, and the floor spec.

    `must_serve` is False on every request, and that is a substantive modelling
    choice rather than a convenience: the ADA complementary-paratransit mandate
    attaches to NEXT-DAY service, which a same-day commingled product does not
    replace and does not discharge. A same-day trip is discretionary, which is
    exactly why an operator can decline one -- and exactly why it is worth
    measuring who gets declined.
    """
    rng = random.Random(f"commingled/{darp_instance.name}/{seed}")
    n = darp_instance.num_requests
    depot = darp_instance.nodes[darp_instance.depot_start]
    base = datetime(2026, 7, 24, 6, 0, tzinfo=timezone.utc)

    def at(minute: float) -> datetime:
        return base + timedelta(minutes=float(minute))

    # FLEET SIZE AND CAPACITY ARE PARAMETERS, and that is not a convenience knob.
    # The routing instance's own K and Q describe a NEXT-DAY problem in which a
    # vehicle also spends its day driving between stops. This IR has no travel
    # between trips, so carrying K and Q over unchanged models a fleet that is
    # idle ~90% of the day, no request ever contends with another, and the
    # exposure measurement correctly reports zero -- having measured nothing. A
    # same-day service is capacity-limited by construction; the fleet is the
    # variable that says how limited, and the report carries the value used.
    K = num_vehicles if num_vehicles is not None else darp_instance.num_vehicles
    Q = vehicle_capacity if vehicle_capacity is not None else darp_instance.vehicle_capacity
    n_accessible = accessible_vehicles if accessible_vehicles is not None else max(1, K // 2)
    vehicles: list[DecisionVehicle] = []
    for k in range(K):
        accessible = k < n_accessible
        vehicles.append(
            DecisionVehicle(
                vehicle_id=_seeded_id(VehicleId, rng),
                capacity_ambulatory=Q,
                capacity_wheelchair=1 if accessible else 0,
                shift_start=at(depot.tw_start),
                shift_end=at(depot.tw_end),
            )
        )

    requests: list[RideRequest] = []
    booked: list[tuple[str, datetime]] = []
    # Deterministic cohort assignment: a shuffled index list rather than an
    # independent coin per request, so the wheelchair SHARE is exact at every
    # instance size instead of merely expected. An instance that happened to draw
    # zero wheelchair riders would make the accessibility breakdown vacuous.
    order = list(range(1, n + 1))
    rng.shuffle(order)
    wheelchair_requests = set(order[: round(wheelchair_share * n)])

    for r in range(1, n + 1):
        p = darp_instance.nodes[darp_instance.pickup_index(r)]
        d = darp_instance.nodes[darp_instance.dropoff_index(r)]
        ride = max(1.0, darp_instance.dist(darp_instance.pickup_index(r), darp_instance.dropoff_index(r)))
        shift_span = depot.tw_end - depot.tw_start
        # Cordeau type-a instances put a tight window on ONE end of each request
        # and leave the other open (outbound trips are constrained at the
        # drop-off, inbound at the pickup). Both are mapped onto the IR's
        # pickup-window vocabulary without inventing tightness that is not there.
        if (p.tw_end - p.tw_start) <= shift_span:
            pw_start, pw_end = at(p.tw_start), at(p.tw_end)
            dw_end = at(min(depot.tw_end, p.tw_end + darp_instance.max_ride_time))
        else:
            pw_start = at(max(depot.tw_start, d.tw_start - ride - darp_instance.max_ride_time))
            pw_end = at(max(depot.tw_start, d.tw_end - ride))
            dw_end = at(d.tw_end)
        if pw_end < pw_start:
            pw_end = pw_start
        rid = _seeded_id(RequestId, rng)
        requests.append(
            RideRequest(
                request_id=rid,
                pickup_window_start=pw_start,
                pickup_window_end=pw_end,
                dropoff_window_end=max(dw_end, pw_end + timedelta(minutes=ride)),
                needs_wheelchair=r in wheelchair_requests,
                party_size=1,
                nominal_ride_time_minutes=round(ride, 3),
                max_ride_time_minutes=float(darp_instance.max_ride_time),
                must_serve=False,
            )
        )
        lead = rng.randint(min_lead_minutes, max_lead_minutes)
        booked.append((str(rid), pw_start - timedelta(minutes=lead)))

    # Denial must dominate: the objective is trips first, minutes second.
    total_ride = sum(r.nominal_ride_time_minutes for r in requests)
    policy = DecisionPolicy(
        policy_id=_seeded_id(PolicyId, rng),
        name=f"commingled-{darp_instance.name}",
        time_granularity_minutes=time_granularity_minutes,
        unserved_penalty=float(round(total_ride + 1000.0)),
        ride_time_weight=1.0,
        # The v0.1 hand-rolled backends are never dispatched to on these
        # instances; the field is kept at its floor because the IR requires >= 1.
        exact_max_requests=1,
    )
    problem = DecisionProblem(
        tenant_id=_seeded_id(TenantId, rng),
        policy=policy,
        vehicles=tuple(vehicles),
        requests=tuple(requests),
    )
    assert_denial_dominates(problem)
    fleet = CommingledFleet.from_problem(problem, wheelchair_footprint=wheelchair_footprint)

    provenance = InstanceProvenance(
        source=darp_instance.name,
        timing_from=(
            "Cordeau (2006) dial-a-ride instance file, unchanged: request count, vehicle count, "
            "depot/shift window, 15-minute service windows, max ride time, vehicle capacity, and "
            "each request's direct pickup-to-drop-off Euclidean travel time as its nominal ride"
        ),
        accessibility_labels=(
            f"ASSIGNED by this harness from seed {seed}: exactly {round(wheelchair_share * n)} of "
            f"{n} requests need a wheelchair-accessible vehicle, and {n_accessible} of {K} vehicles "
            f"carry a wheelchair position. The source instances carry NO accessibility attribute. "
            f"These labels are a modelling assumption and are not evidence about any real rider."
        ),
        fleet_sizing=(
            f"{K} vehicles of ambulatory capacity {Q}"
            + (
                " -- taken from the instance file."
                if num_vehicles is None and vehicle_capacity is None
                else f" -- OVERRIDDEN from the instance's own {darp_instance.num_vehicles}x"
                     f"{darp_instance.vehicle_capacity}. This IR models no travel between trips, so "
                     f"the instance's own fleet is idle most of the day and nothing contends; the "
                     f"override is what makes the service capacity-limited, as a same-day service "
                     f"is. It is an assumption about the operator, not a measurement of one."
            )
        ),
        booking_times=(
            f"ASSIGNED: each request booked a seeded {min_lead_minutes}-{max_lead_minutes} minutes "
            f"before its pickup window opens. Arrival ORDER is the variable the online scheduler "
            f"cannot control, so it is swept across seeds rather than fixed."
        ),
        fleet_floor=(
            f"ASSIGNED: floor units default to the vehicle's ambulatory seat count ({Q}), widened "
            f"where a declared wheelchair position would not otherwise fit; a deployed wheelchair "
            f"station occupies {wheelchair_footprint} seat-equivalents."
        ),
        wheelchair_share=wheelchair_share,
        seed=seed,
    )
    return CommingledInstance(
        problem=problem,
        fleet=fleet,
        booked_at=tuple(booked),
        provenance=provenance,
    )
