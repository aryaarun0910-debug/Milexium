"""The compatibility graph: which trips can share, at what cost, and who decides.

WHY THIS MODULE EXISTS. Across US agencies reporting passenger miles in both
years, 2015 -> 2024 average trip length FELL 4.6% while occupancy fell 10.0%
(1.213 -> 1.092 passenger miles per vehicle mile). The productivity collapse is
LOST RIDE-SHARING, not longer trips. Occupancy is not a fact about riders; it is
the thing a scheduling system decides, one shared ride at a time. This module is
the object that decision needs: an explicit graph over requests in which an edge
means "these two trips can feasibly share" and a hyperedge means "these k trips
can", each carrying the cost of the share and a materialised proof that it is
feasible.

**FRAMING, fixed and load-bearing. This is about RELEASING capacity, never
rationing it.** A pooling model that found its efficiency by serving fewer riders
would be a failure, not a result -- restricting transit use is not the objective.
Occupancy here rises only by putting riders who would have travelled anyway into
the same vehicle; nothing in this package declines a rider it could serve, and
the planner built on it (`packages.decide.pooling`) reuses the online harness's
structural refusal to run a rationing policy. Every evaluation in this packet
reports trips served alongside occupancy for exactly that reason: an occupancy
number that went up while trips served went down is a defect report.

THE SEPARATION THIS MODULE IS BUILT AROUND.

A scorer may PROPOSE promising combinations. Only the feasibility authority may
ESTABLISH that one is feasible. That is enforced structurally, not by convention:

- A scorer is handed a `ProposalView` and returns a `float`. `ProposalView`
  carries coordinates, windows, direct ride times and mobility needs -- and no
  schedule, no violation list, and no certificate field. The scorer's input type
  cannot express a feasibility verdict and its output type cannot carry one, so a
  scorer has no vocabulary in which to bless anything.
- A share becomes real only as a `Certificate`, whose `__post_init__` demands a
  module-private witness token. `certify_group` and `certify_insertion` are the
  only functions that hold it, and they mint one only after BOTH independent
  checkers -- `packages.decide.feasibility.check_darp_feasibility` (unmodified,
  imported) and `check_equipment_feasibility` below -- return no violations on a
  concrete schedule.
- A `Certificate` carries its witness schedule, so the proof travels with the
  claim and `recheck()` re-runs both checkers from the raw instance.
  `CompatibilityGraph` re-verifies every certificate at admission by default, so
  a forged certificate is not merely discouraged, it is rejected.

The consequence worth stating plainly: a better scorer changes WHICH shares get
examined and in what order. It can never change which shares are feasible, and it
cannot make an infeasible share enter the graph. Swap in a learned model, a
random number generator, or an adversary that scores infeasible groups highest --
the graph's contents are identical up to enumeration order and budget.

**No learned model is shipped here.** `geometric_affinity` is a hand-written
heuristic and says so. The interface is the deliverable; a trained ranker plugs
into it and gains no authority by being trained.

AN EDGE MEANS A SHARED RIDE, NOT A SHARED ROUTE. A vehicle that carries A to
their door and then drives to B's origin has served two trips on one route and
shared nothing: occupancy is unchanged and none of the sector's lost ride-sharing
is recovered. So `certify_group` admits only orderings on which the group is
genuinely POOLED (`shares_a_ride`, which requires the onboard-overlap graph to be
connected). This is not cosmetic. Without it the equipment layer below is INERT --
two wheelchair riders who are never aboard together never contend for the one
position -- and the first build of this module duly reported zero equipment
contention on every instance it was run on.

EQUIPMENT IS NOT FUNGIBLE, and this module is where that stops being a slogan.
`packages.decide.feasibility.check_darp_feasibility` sweeps the instance's signed
integer load and knows nothing about mobility devices -- under it a wheelchair
user is one unit of load like anyone else, so every ride-share is equally
available to them and the interesting question is vacuous by construction. The
additive layer here says two things the integer sweep cannot:

    a wheelchair rider requires a vehicle with a wheelchair POSITION, and
    a deployed station occupies `wheelchair_footprint` SEAT-EQUIVALENTS of the
    same floor the ambulatory seats are drawn from.

That is the same vehicle model `packages.decide.commingled` uses (a cutaway van
where a station is MADE by folding up a bench), applied to the routed problem
rather than the assignment one. `feasibility.py` is not modified: the equipment
checker is a SUPPLEMENT run alongside it, and a group must pass both.

ACCESSIBILITY LABELS ON THESE INSTANCES ARE ASSIGNED, NOT OBSERVED. The published
Cordeau dial-a-ride files carry no accessibility attribute whatsoever (ADR-0065).
`assign_accessibility` invents the wheelchair/ambulatory split and the accessible
share of the fleet from a seed. Results therefore support ALGORITHMIC claims only
-- that the graph is built correctly, that the authority holds, that the
stratification discriminates -- and say NOTHING about any real fleet's riders.
Every report emitted from this package repeats that; it must not be dropped.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field, replace
from random import Random
from typing import Callable, Iterable, Sequence

from packages.canonical.vocab import ReasonCode
from packages.decide.cpsat_darp import exact_schedule
from packages.decide.darp_ir import DarpInstance, DarpRoute, DarpSolution, DarpVisit
from packages.decide.darp_solver import route_distance
from packages.decide.feasibility import DarpViolation, check_darp_feasibility

COMPATIBILITY_VERSION = "0.5.0"

ASSIGNED_ACCESSIBILITY_NOTE = (
    "ASSIGNED, NOT OBSERVED: the published Cordeau dial-a-ride instance files carry no "
    "accessibility attribute at all, so the wheelchair/ambulatory split, the accessible share of "
    "the fleet, the wheelchair-station footprint and the position count are all invented here from "
    "a seed. They are modelling assumptions. Nothing derived from them is evidence about any real "
    "operator's riders, vehicles or service. See ADR-0065."
)

_DEFAULT_WHEELCHAIR_FOOTPRINT = 2
"""Seat-equivalents a deployed wheelchair station occupies, matching
`packages.decide.commingled._DEFAULT_WHEELCHAIR_FOOTPRINT`. Two is the common
cutaway/minivan case -- a station replaces a two-seat bench. A PARAMETER, not a
constant: a fleet whose stations sit in dedicated floor space has a footprint of
0 against the ambulatory seats, and under that value this layer correctly reports
no equipment contention at all."""


class UncertifiedGroup(RuntimeError):
    """Someone tried to construct a `Certificate` without the authority's witness.

    Raised, never returned. A `Certificate` asserts that two independent checkers
    accepted a concrete schedule; a value asserting that without either checker
    having run is not a weaker claim, it is a false one.
    """


# ==========================================================================
# Accessibility: an additive layer over an instance that carries none.
# ==========================================================================

@dataclass(frozen=True)
class AccessibilityProfile:
    """Who needs a wheelchair-accessible vehicle, which vehicles are one, and
    what a deployed station costs against the shared floor.

    `provenance` is carried on the object rather than left to a report to
    remember, because an equipment-contention number separated from the fact that
    its labels were invented is not interpretable.
    """

    instance_name: str
    num_requests: int
    num_vehicles: int
    wheelchair_requests: frozenset[int]
    accessible_vehicles: frozenset[int]
    wheelchair_positions: int = 1
    wheelchair_footprint: int = _DEFAULT_WHEELCHAIR_FOOTPRINT
    seed: int = 0
    wheelchair_share: float = 0.0
    provenance: str = ASSIGNED_ACCESSIBILITY_NOTE

    def needs_wheelchair(self, request: int) -> bool:
        return request in self.wheelchair_requests

    def is_accessible(self, vehicle: int) -> bool:
        return vehicle in self.accessible_vehicles

    def positions_on(self, vehicle: int) -> int:
        return self.wheelchair_positions if self.is_accessible(vehicle) else 0

    def floor_units(self, instance: DarpInstance, request: int) -> int:
        """Seat-equivalents this rider occupies while onboard. A wheelchair rider
        costs the station's footprint; anyone else costs their party size, which
        is the instance's own pickup load."""
        if self.needs_wheelchair(request):
            return self.wheelchair_footprint
        return abs(instance.nodes[instance.pickup_index(request)].load)

    def riders(self, instance: DarpInstance, request: int) -> int:
        """PEOPLE this request puts in the vehicle. Deliberately NOT the same as
        `floor_units`: passenger miles count people, capacity counts floor. A
        wheelchair rider occupying two seat-equivalents is still one passenger,
        and conflating the two would inflate every occupancy number here."""
        return abs(instance.nodes[instance.pickup_index(request)].load)

    def can_bind(self, instance: DarpInstance) -> bool:
        """Is this layer CAPABLE of forbidding something the raw integer-load
        checker would allow on this instance?

        Exists so a suite can refuse to draw conclusions from a configuration in
        which the constraint under study is inert. An earlier packet in this
        repository shipped a pairing constraint that was vacuous at K=1 while
        every test instance happened to be K=1; this is the guard against
        repeating that with equipment contention. It is a statement about the
        CONFIGURATION, not about any particular solution -- `bound_by_equipment`
        below answers whether it actually bit.
        """
        if not self.wheelchair_requests:
            return False
        if len(self.accessible_vehicles) < self.num_vehicles:
            return True  # some vehicle cannot carry a wheelchair rider at all
        if self.wheelchair_positions < instance.vehicle_capacity:
            return True  # positions run out before seats do
        return any(
            self.wheelchair_footprint > abs(instance.nodes[instance.pickup_index(r)].load)
            for r in self.wheelchair_requests
        )

    def to_record(self) -> dict:
        return {
            "instance": self.instance_name,
            "ASSIGNED_wheelchair_requests": sorted(self.wheelchair_requests),
            "ASSIGNED_accessible_vehicles": sorted(self.accessible_vehicles),
            "ASSIGNED_wheelchair_positions_per_accessible_vehicle": self.wheelchair_positions,
            "ASSIGNED_wheelchair_station_footprint_seat_equivalents": self.wheelchair_footprint,
            "ASSIGNED_wheelchair_share": self.wheelchair_share,
            "seed": self.seed,
            "provenance": self.provenance,
        }


def assign_accessibility(
    instance: DarpInstance,
    *,
    seed: int,
    wheelchair_share: float = 0.35,
    accessible_vehicles: int | None = None,
    wheelchair_positions: int = 1,
    wheelchair_footprint: int = _DEFAULT_WHEELCHAIR_FOOTPRINT,
) -> AccessibilityProfile:
    """Invent an accessibility profile for a published instance that has none.

    The share is EXACT rather than expected: a shuffled index list, not an
    independent coin per request. An instance that happened to draw zero
    wheelchair riders would make every stratified number in this packet vacuous,
    and "we got unlucky" is not a defensible reason for a suite to prove nothing.

    Read `ASSIGNED_ACCESSIBILITY_NOTE`. Everything this function returns is a
    modelling assumption.
    """
    if not 0.0 <= wheelchair_share <= 1.0:
        raise ValueError(f"wheelchair_share must be in [0, 1], got {wheelchair_share}")
    rng = Random(f"accessibility/{instance.name}/{seed}")
    order = list(range(1, instance.num_requests + 1))
    rng.shuffle(order)
    chosen = frozenset(order[: round(wheelchair_share * instance.num_requests)])
    k = instance.num_vehicles
    n_acc = accessible_vehicles if accessible_vehicles is not None else max(1, k // 2)
    n_acc = max(0, min(k, n_acc))
    return AccessibilityProfile(
        instance_name=instance.name,
        num_requests=instance.num_requests,
        num_vehicles=k,
        wheelchair_requests=chosen,
        accessible_vehicles=frozenset(range(n_acc)),
        wheelchair_positions=wheelchair_positions,
        wheelchair_footprint=wheelchair_footprint,
        seed=seed,
        wheelchair_share=wheelchair_share,
    )


# ==========================================================================
# The equipment checker: a SUPPLEMENT to the independent DARP checker.
#
# Written as a sweep over a finished route, deliberately separate from the
# incremental pruning any generator does. Same discipline as
# `commingled._floor_fits` vs `commingled.check_floor_feasibility`: a generator
# that graded its own homework would not be a check.
# ==========================================================================

def check_equipment_feasibility(
    instance: DarpInstance,
    profile: AccessibilityProfile,
    solution: DarpSolution,
) -> list[DarpViolation]:
    """Every equipment violation in `solution`, re-derived from the raw instance.

    Three things the integer-load checker cannot see:

    1. A wheelchair rider on a vehicle with no wheelchair position.
    2. More wheelchair riders onboard at once than the vehicle has positions.
    3. A floor over-subscribed once a deployed station is charged its real
       footprint in seat-equivalents.

    Returns violations rather than raising, so one pass enumerates all of them,
    matching `check_darp_feasibility`'s contract exactly. This NEVER replaces that
    checker -- a routed group must pass both, and `certify_group` runs both.
    """
    depot = {instance.depot_start, instance.depot_end}
    out: list[DarpViolation] = []
    for route in solution.routes:
        v = route.vehicle
        positions = profile.positions_on(v)
        floor = instance.vehicle_capacity
        onboard_wc = 0
        onboard_floor = 0
        for visit in route.visits:
            i = visit.node_index
            if i in depot:
                continue
            r = instance.request_of(i)
            wc = profile.needs_wheelchair(r)
            units = profile.floor_units(instance, r)
            if instance.is_pickup(i):
                if wc and positions < 1:
                    out.append(
                        DarpViolation(
                            ReasonCode.NO_ACCESSIBLE_CAPACITY,
                            f"request {r} needs a wheelchair-accessible vehicle; vehicle {v} has no "
                            f"wheelchair position",
                            v,
                            i,
                            r,
                        )
                    )
                onboard_wc += 1 if wc else 0
                onboard_floor += units
            else:
                onboard_wc -= 1 if wc else 0
                onboard_floor -= units
            if onboard_wc > positions:
                out.append(
                    DarpViolation(
                        ReasonCode.NO_ACCESSIBLE_CAPACITY,
                        f"{onboard_wc} wheelchair riders onboard vehicle {v} which has "
                        f"{positions} position(s)",
                        v,
                        i,
                        r,
                    )
                )
            if onboard_floor > floor:
                out.append(
                    DarpViolation(
                        ReasonCode.NO_ACCESSIBLE_CAPACITY,
                        f"floor load {onboard_floor} seat-equivalents exceeds {floor} on vehicle {v} "
                        f"(wheelchair station footprint {profile.wheelchair_footprint})",
                        v,
                        i,
                        r,
                    )
                )
    return out


def bound_by_equipment(
    instance: DarpInstance,
    profile: AccessibilityProfile,
    solution: DarpSolution,
) -> bool:
    """True iff the equipment layer -- and ONLY the equipment layer -- rejects
    this solution. The witness a test needs to prove the layer is not inert."""
    return bool(check_equipment_feasibility(instance, profile, solution)) and not check_darp_feasibility(
        instance, solution
    )


# ==========================================================================
# THE FEASIBILITY AUTHORITY.
#
# Everything above this line describes constraints. Everything below decides,
# and it is the only thing in this package permitted to.
# ==========================================================================

_WITNESS = object()
"""The authority's private token. `Certificate.__post_init__` refuses any value
that is not this object, so a `Certificate` cannot come into existence except
through `_mint`, which runs both checkers first. Python cannot make this
unforgeable, and this module does not pretend it can -- what it does is make the
forgery require reaching into a private module attribute by name, and make it
USELESS, because `CompatibilityGraph` re-runs both checkers on admission."""


@dataclass(frozen=True)
class Certificate:
    """A materialised feasibility proof for one group of requests on one vehicle.

    Carries the WITNESS -- the node sequence and the concrete begin-service time
    at each stop -- rather than a boolean, so the claim travels with its evidence
    and `recheck` can re-derive the verdict from the raw instance. A certificate
    whose schedule does not survive re-checking is not a weaker certificate; it is
    a forgery, and `CompatibilityGraph` rejects it.

    `checked_by` names every checker that returned zero violations. Both must
    appear: the routing checker knows nothing about mobility devices and the
    equipment checker knows nothing about time windows.
    """

    request_ids: tuple[int, ...]
    vehicle: int
    sequence: tuple[int, ...]
    begin_service: tuple[float, ...]
    checked_by: tuple[str, ...]
    witness: object = field(repr=False, compare=False, default=None)

    def __post_init__(self) -> None:
        if self.witness is not _WITNESS:
            raise UncertifiedGroup(
                "a Certificate asserts that two independent checkers accepted a concrete schedule; "
                "it cannot be constructed without the authority's witness. Call certify_group() or "
                "certify_insertion()."
            )

    @property
    def order(self) -> int:
        return len(self.request_ids)

    def as_route(self) -> DarpRoute:
        return DarpRoute(
            vehicle=self.vehicle,
            visits=tuple(
                DarpVisit(node_index=s, begin_service=self.begin_service[k])
                for k, s in enumerate(self.sequence)
            ),
        )

    def recheck(self, instance: DarpInstance, profile: AccessibilityProfile) -> list[DarpViolation]:
        """Re-run BOTH independent checkers on the witness schedule. An empty list
        means the proof still stands when re-derived from the raw instance."""
        probe = _probe(instance, self.as_route())
        return list(check_darp_feasibility(instance, probe)) + list(
            check_equipment_feasibility(instance, profile, probe)
        )

    def to_record(self) -> dict:
        return {
            "request_ids": list(self.request_ids),
            "vehicle": self.vehicle,
            "sequence": list(self.sequence),
            "begin_service": [round(b, 6) for b in self.begin_service],
            "checked_by": list(self.checked_by),
        }


@dataclass(frozen=True)
class CertificationOutcome:
    """What the authority decided, and which checker decided it.

    `rejected_by` exists so a suite can prove the equipment layer is doing work
    rather than riding along behind the routing checker. A layer that never
    appears in a rejection is a layer that has not been tested.
    """

    request_ids: tuple[int, ...]
    vehicle: int
    certificate: Certificate | None
    sequences_tried: int
    rejected_by: tuple[str, ...]
    violations: tuple[DarpViolation, ...]
    detail: str

    @property
    def certified(self) -> bool:
        return self.certificate is not None


_ROUTING_CHECKER = "feasibility.check_darp_feasibility"
_EQUIPMENT_CHECKER = "compatibility.check_equipment_feasibility"
_SCHEDULER = "cpsat_darp.exact_schedule"
"""Recorded distinctly from the two checkers. `exact_schedule` returning None
means the ordering's difference-constraint system has no solution at all, so no
schedule ever reached a checker -- a different fact from "a schedule existed and a
checker rejected it", and collapsing the two would hide whether the equipment
layer is doing any work."""


def _probe(instance: DarpInstance, route: DarpRoute) -> DarpSolution:
    """A one-route solution object, so the INDEPENDENT checkers judge a candidate
    on exactly the terms they judge any finished plan. Deliberately not a private
    re-implementation of the constraints: a checker and a generator that each keep
    their own copy of the rules drift into agreeing with each other and no one
    else. (`cpsat_darp._route_ok` uses the same trick for the same reason.)"""
    return DarpSolution(
        instance_name=instance.name,
        num_requests=instance.num_requests,
        routes=(route,),
        status="probe",
        objective=None,
        served_requests=(),
        solver_name="milexium-decide-compatibility",
        solver_version=COMPATIBILITY_VERSION,
        seed=0,
    )


def _mint(
    instance: DarpInstance,
    profile: AccessibilityProfile,
    request_ids: tuple[int, ...],
    vehicle: int,
    sequence: Sequence[int],
    begin: Sequence[float],
) -> tuple[Certificate | None, tuple[str, ...], tuple[DarpViolation, ...]]:
    """Run both independent checkers on a concrete schedule and mint a
    `Certificate` if and only if both return nothing. The single place the witness
    token is used."""
    route = DarpRoute(
        vehicle=vehicle,
        visits=tuple(DarpVisit(node_index=s, begin_service=float(begin[k])) for k, s in enumerate(sequence)),
    )
    probe = _probe(instance, route)
    routing = check_darp_feasibility(instance, probe)
    equipment = check_equipment_feasibility(instance, profile, probe)
    rejected: list[str] = []
    if routing:
        rejected.append(_ROUTING_CHECKER)
    if equipment:
        rejected.append(_EQUIPMENT_CHECKER)
    if rejected:
        return None, tuple(rejected), tuple(routing) + tuple(equipment)
    return (
        Certificate(
            request_ids=request_ids,
            vehicle=vehicle,
            sequence=tuple(sequence),
            begin_service=tuple(float(b) for b in begin),
            checked_by=(_ROUTING_CHECKER, _EQUIPMENT_CHECKER),
            witness=_WITNESS,
        ),
        (),
        (),
    )


def onboard_profile(instance: DarpInstance, sequence: Sequence[int]) -> list[int]:
    """People aboard on each arc of `sequence` (arc k runs sequence[k] ->
    sequence[k+1]). The primitive both the occupancy metric and the shared-ride
    test are derived from."""
    onboard = 0
    out: list[int] = []
    for a in sequence[:-1]:
        if instance.is_pickup(a):
            onboard += abs(instance.nodes[a].load)
        elif instance.is_dropoff(a):
            onboard -= abs(instance.nodes[a].load)
        out.append(onboard)
    return out


def shares_a_ride(instance: DarpInstance, sequence: Sequence[int], request_ids: Sequence[int]) -> bool:
    """Are these riders actually POOLED on this sequence, or merely consolidated?

    This distinction is the whole packet. A vehicle that carries request A to its
    door, then drives to B's origin and carries B, has served two trips on one
    route and shared NOTHING: occupancy is unchanged and the sector's lost
    ride-sharing is not recovered by it. A compatibility edge that counted such a
    sequence would be measuring route consolidation while claiming to measure
    pooling -- and it would also make the equipment layer inert, because two
    wheelchair riders never onboard at once never contend for the one position.

    The test: build the graph whose vertices are the group's requests and whose
    edges join riders whose onboard intervals overlap, and require it CONNECTED.
    For a pair that is simply "both aboard at once". For a triple it admits A+B
    then B+C, which is a genuine pooled ride through B, while rejecting three
    trips run back to back.
    """
    ids = list(request_ids)
    if len(ids) < 2:
        return True
    pos = {node: i for i, node in enumerate(sequence)}
    span = {
        r: (pos[instance.pickup_index(r)], pos[instance.dropoff_index(r)])
        for r in ids
    }
    adj: dict[int, set[int]] = {r: set() for r in ids}
    for a, b in itertools.combinations(ids, 2):
        (pa, da), (pb, db) = span[a], span[b]
        if pa < db and pb < da:  # half-open intervals overlap
            adj[a].add(b)
            adj[b].add(a)
    seen = {ids[0]}
    stack = [ids[0]]
    while stack:
        cur = stack.pop()
        for nxt in adj[cur]:
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return len(seen) == len(ids)


def _interleavings(
    instance: DarpInstance, request_ids: Sequence[int], *, require_shared_ride: bool
) -> list[list[int]]:
    """Every pickup-before-drop-off ordering of a group, as full depot-anchored
    node sequences. 2 requests -> 6 orderings, 3 -> 90, 4 -> 2520; the caller
    bounds the group size, and `max_sequences` bounds the work.

    With `require_shared_ride` (the default everywhere the graph is built), only
    orderings on which the group is genuinely pooled survive -- see
    `shares_a_ride` for why that is not a cosmetic filter.
    """
    nodes = [instance.pickup_index(r) for r in request_ids] + [
        instance.dropoff_index(r) for r in request_ids
    ]
    out: list[list[int]] = []
    for perm in itertools.permutations(nodes):
        pos = {node: i for i, node in enumerate(perm)}
        if not all(pos[instance.pickup_index(r)] < pos[instance.dropoff_index(r)] for r in request_ids):
            continue
        if require_shared_ride and not shares_a_ride(instance, perm, request_ids):
            continue
        out.append([instance.depot_start, *perm, instance.depot_end])
    return out


def certify_group(
    instance: DarpInstance,
    profile: AccessibilityProfile,
    request_ids: Sequence[int],
    vehicle: int,
    *,
    max_sequences: int | None = None,
    require_shared_ride: bool = True,
) -> CertificationOutcome:
    """Can this group of requests SHARE a ride on `vehicle`? THE AUTHORITY.

    Enumerates pickup-before-drop-off orderings cheapest-first by raw distance,
    schedules each exactly (`cpsat_darp.exact_schedule`, the difference-constraint
    least fixpoint), and offers the result to BOTH independent checkers. The first
    ordering both accept wins; distance-ordered enumeration makes that the
    cheapest certified sharing sequence, not merely some certified one.

    `require_shared_ride` (default True) restricts the enumeration to orderings on
    which the riders are actually pooled. Turning it off answers the different,
    weaker question "can one vehicle serve all of these on one route", which is
    route consolidation and does not raise occupancy. The default is True because
    the packet is about pooling, and because sequential service is exactly the
    case in which the equipment layer can never bite -- two wheelchair riders who
    are never aboard together never contend for the one position, so a graph built
    without this filter would report zero equipment contention and mean nothing
    by it.

    Returns an outcome, never a bare bool, so a caller can see how much was tried
    and WHICH checker objected. `certificate is None` means no examined ordering
    survived -- with `max_sequences` unset that is exhaustive over the admissible
    orderings, which is a genuine infeasibility verdict for pooling this group on
    this vehicle.
    """
    ids = tuple(sorted(int(r) for r in request_ids))
    if not ids:
        raise ValueError("a group must contain at least one request")
    if len(set(ids)) != len(ids):
        raise ValueError(f"duplicate request in group {ids}")
    for r in ids:
        if not 1 <= r <= instance.num_requests:
            raise ValueError(f"request {r} is not in {instance.name} (1..{instance.num_requests})")

    seqs = _interleavings(instance, ids, require_shared_ride=require_shared_ride)
    seqs.sort(key=lambda s: (route_distance(instance, s), s))
    if max_sequences is not None:
        seqs = seqs[:max_sequences]

    # Accumulated over EVERY ordering tried, not just the last one. A per-attempt
    # overwrite would report whichever gate happened to speak last and would make
    # "the equipment layer rejected nothing" unfalsifiable.
    rejected_by: set[str] = set()
    violations: list[DarpViolation] = []
    tried = 0
    for seq in seqs:
        tried += 1
        begin = exact_schedule(instance, seq)
        if begin is None:
            rejected_by.add(_SCHEDULER)
            continue
        cert, who, vio = _mint(instance, profile, ids, vehicle, seq, begin)
        if cert is not None:
            return CertificationOutcome(
                request_ids=ids,
                vehicle=vehicle,
                certificate=cert,
                sequences_tried=tried,
                rejected_by=(),
                violations=(),
                detail=f"certified on the cheapest of {tried} ordering(s) accepted by both checkers",
            )
        rejected_by.update(who)
        violations.extend(vio)

    exhaustive = max_sequences is None
    if not seqs:
        rejected_by.add(_SCHEDULER)
    return CertificationOutcome(
        request_ids=ids,
        vehicle=vehicle,
        certificate=None,
        sequences_tried=tried,
        rejected_by=tuple(sorted(rejected_by)),
        violations=tuple(violations[:20]),
        detail=(
            f"no ordering of {ids} on vehicle {vehicle} survived both checkers "
            f"({tried} tried, {'exhaustive' if exhaustive else 'BOUNDED -- absence is not proof'})"
        ),
    )


def certify_insertion(
    instance: DarpInstance,
    profile: AccessibilityProfile,
    vehicle: int,
    current_sequence: Sequence[int],
    request: int,
) -> CertificationOutcome:
    """Cheapest certified way to add one request to an EXISTING route, or none.

    The planner's inner loop. Same authority, same two checkers, same witness --
    an insertion is not a weaker kind of feasibility claim than a group is, so it
    does not get a weaker gate. Positions are enumerated in full (no pruning
    heuristic decides what the checkers get to see) and the cheapest surviving one
    wins, so the returned certificate is the minimum-detour feasible insertion,
    not merely a feasible one.
    """
    seq = list(current_sequence)
    if len(seq) < 2 or seq[0] != instance.depot_start or seq[-1] != instance.depot_end:
        raise ValueError(f"route must be depot-anchored, got {seq[:2]}..{seq[-2:]}")
    p = instance.pickup_index(request)
    d = instance.dropoff_index(request)
    if p in seq or d in seq:
        raise ValueError(f"request {request} is already on vehicle {vehicle}")

    existing = tuple(sorted(instance.request_of(s) for s in seq if instance.is_pickup(s)))
    ids = tuple(sorted(existing + (request,)))

    candidates: list[list[int]] = []
    for pi in range(1, len(seq)):
        with_p = seq[:pi] + [p] + seq[pi:]
        for di in range(pi + 1, len(with_p)):
            candidates.append(with_p[:di] + [d] + with_p[di:])
    candidates.sort(key=lambda s: (route_distance(instance, s), s))

    rejected_by: set[str] = set()
    violations: list[DarpViolation] = []
    tried = 0
    for cand in candidates:
        tried += 1
        begin = exact_schedule(instance, cand)
        if begin is None:
            rejected_by.add(_SCHEDULER)
            continue
        cert, who, vio = _mint(instance, profile, ids, vehicle, cand, begin)
        if cert is not None:
            return CertificationOutcome(
                request_ids=ids,
                vehicle=vehicle,
                certificate=cert,
                sequences_tried=tried,
                rejected_by=(),
                violations=(),
                detail=f"cheapest certified insertion of request {request} out of {tried} position(s) tried",
            )
        rejected_by.update(who)
        violations.extend(vio)

    return CertificationOutcome(
        request_ids=ids,
        vehicle=vehicle,
        certificate=None,
        sequences_tried=tried,
        rejected_by=tuple(sorted(rejected_by)),
        violations=tuple(violations[:20]),
        detail=(
            f"request {request} admits no certified insertion into vehicle {vehicle} "
            f"({tried} position pair(s) tried, exhaustive)"
        ),
    )


def admits_insertion(
    instance: DarpInstance,
    profile: AccessibilityProfile,
    vehicle: int,
    current_sequence: Sequence[int],
    request: int,
) -> bool:
    """Does ANY certified insertion of `request` into this route exist?

    Existence only, short-circuiting on the first position both checkers accept.
    Same authority, same two checkers, same `_mint` -- it differs from
    `certify_insertion` in stopping early, never in what it will accept. Exists
    because `packages.decide.capacity_value` asks this question thousands of times
    and only ever reads the boolean; building the cheapest insertion each time
    would be the difference between a capacity estimate that runs inside a
    planning loop and one that does not.
    """
    seq = list(current_sequence)
    p, d = instance.pickup_index(request), instance.dropoff_index(request)
    if p in seq or d in seq:
        return True
    existing = tuple(sorted(instance.request_of(s) for s in seq if instance.is_pickup(s)))
    ids = tuple(sorted(existing + (request,)))
    for pi in range(1, len(seq)):
        with_p = seq[:pi] + [p] + seq[pi:]
        for di in range(pi + 1, len(with_p)):
            cand = with_p[:di] + [d] + with_p[di:]
            begin = exact_schedule(instance, cand)
            if begin is None:
                continue
            cert, _who, _vio = _mint(instance, profile, ids, vehicle, cand, begin)
            if cert is not None:
                return True
    return False


# ==========================================================================
# What a share costs. Derived from the WITNESS, never from a solver's report.
# ==========================================================================

@dataclass(frozen=True)
class ShareFeatures:
    """The cost of one certified share, computed from its witness schedule.

    Every field is re-derived from the instance and the certificate's own
    begin-service times. Nothing is taken from whichever search proposed the
    group, which is what makes these numbers comparable across scorers.

    `future_capacity_cost` and `future_accessible_capacity_cost` are left None
    here on purpose. They are the only fields that require a view of demand that
    has not arrived yet, they cost orders of magnitude more to compute than the
    rest, and they are an ESTIMATE where everything else is exact.
    `packages.decide.capacity_value.attach_capacity_features` fills them in when a
    caller wants them, and the None default means an unfilled estimate can never
    be mistaken for a computed zero.
    """

    vehicle_miles: float
    solo_vehicle_miles: float
    vehicle_miles_saved: float
    passenger_miles: float
    occupancy: float
    added_detour_minutes: float
    ride_time_minutes: tuple[tuple[int, float], ...]
    direct_minutes: tuple[tuple[int, float], ...]
    worst_ride_time_slack_minutes: float
    window_slack_consumed_minutes: float
    peak_floor_units: int
    floor_capacity: int
    wheelchair_riders: int
    wheelchair_positions: int
    requires_accessible_vehicle: bool
    equipment_contention: float
    overlapping_pairs: int
    shared_vehicle_miles: float
    future_capacity_cost: float | None = None
    future_accessible_capacity_cost: float | None = None

    def to_record(self) -> dict:
        return {
            "vehicle_miles": round(self.vehicle_miles, 6),
            "solo_vehicle_miles": round(self.solo_vehicle_miles, 6),
            "vehicle_miles_saved": round(self.vehicle_miles_saved, 6),
            "passenger_miles": round(self.passenger_miles, 6),
            "occupancy_pax_miles_per_vehicle_mile": round(self.occupancy, 6),
            "added_detour_minutes": round(self.added_detour_minutes, 6),
            "ride_time_minutes": {str(r): round(v, 4) for r, v in self.ride_time_minutes},
            "direct_minutes": {str(r): round(v, 4) for r, v in self.direct_minutes},
            "worst_ride_time_slack_minutes": round(self.worst_ride_time_slack_minutes, 6),
            "window_slack_consumed_minutes": round(self.window_slack_consumed_minutes, 6),
            "peak_floor_units": self.peak_floor_units,
            "floor_capacity": self.floor_capacity,
            "wheelchair_riders": self.wheelchair_riders,
            "wheelchair_positions": self.wheelchair_positions,
            "requires_accessible_vehicle": self.requires_accessible_vehicle,
            "equipment_contention": round(self.equipment_contention, 6),
            "overlapping_pairs": self.overlapping_pairs,
            "shared_vehicle_miles": round(self.shared_vehicle_miles, 6),
            "future_capacity_cost": self.future_capacity_cost,
            "future_accessible_capacity_cost": self.future_accessible_capacity_cost,
        }


def solo_route(instance: DarpInstance, request: int) -> list[int]:
    """The route a request would need entirely to itself: depot, pickup, drop-off,
    depot. The counterfactual every pooling saving is measured against."""
    return [instance.depot_start, instance.pickup_index(request), instance.dropoff_index(request), instance.depot_end]


def route_passenger_miles(
    instance: DarpInstance, profile: AccessibilityProfile, sequence: Sequence[int]
) -> float:
    """Passenger miles on one route: each arc's length times the number of PEOPLE
    aboard for it.

    People, not floor units. A wheelchair rider occupying two seat-equivalents is
    still one passenger, and charging the footprint here would inflate occupancy
    exactly where the packet is trying to measure it honestly.
    """
    aboard = onboard_profile(instance, sequence)
    return sum(
        instance.dist(a, b) * aboard[k] for k, (a, b) in enumerate(zip(sequence, sequence[1:]))
    )


def route_shared_vehicle_miles(instance: DarpInstance, sequence: Sequence[int]) -> float:
    """Miles driven with two or more people aboard. The miles on which pooling
    actually happened, as opposed to the miles a consolidated route merely
    covered."""
    aboard = onboard_profile(instance, sequence)
    return sum(
        instance.dist(a, b)
        for k, (a, b) in enumerate(zip(sequence, sequence[1:]))
        if aboard[k] >= 2
    )


def share_features(
    instance: DarpInstance, profile: AccessibilityProfile, certificate: Certificate
) -> ShareFeatures:
    """Re-derive every feature of a certified share from its witness schedule."""
    seq = list(certificate.sequence)
    begin = list(certificate.begin_service)
    at = {node: i for i, node in enumerate(seq)}
    ids = certificate.request_ids

    vm = route_distance(instance, seq)
    pm = route_passenger_miles(instance, profile, seq)
    solo = sum(route_distance(instance, solo_route(instance, r)) for r in ids)

    rides: list[tuple[int, float]] = []
    directs: list[tuple[int, float]] = []
    detour = 0.0
    worst_slack = math.inf
    for r in ids:
        p, d = instance.pickup_index(r), instance.dropoff_index(r)
        ride = begin[at[d]] - (begin[at[p]] + instance.nodes[p].service_duration)
        direct = instance.dist(p, d)
        rides.append((r, ride))
        directs.append((r, direct))
        detour += ride - direct
        worst_slack = min(worst_slack, instance.max_ride_time - ride)

    consumed = sum(
        begin[i] - instance.nodes[node].tw_start
        for i, node in enumerate(seq)
        if node not in (instance.depot_start, instance.depot_end)
    )

    peak = 0
    floor_now = 0
    for node in seq:
        if instance.is_pickup(node):
            floor_now += profile.floor_units(instance, instance.request_of(node))
        elif instance.is_dropoff(node):
            floor_now -= profile.floor_units(instance, instance.request_of(node))
        peak = max(peak, floor_now)

    overlaps = 0
    for a, b in itertools.combinations(ids, 2):
        pa, da = at[instance.pickup_index(a)], at[instance.dropoff_index(a)]
        pb, db = at[instance.pickup_index(b)], at[instance.dropoff_index(b)]
        if pa < db and pb < da:
            overlaps += 1

    wc = sum(1 for r in ids if profile.needs_wheelchair(r))
    capacity = instance.vehicle_capacity
    return ShareFeatures(
        vehicle_miles=vm,
        solo_vehicle_miles=solo,
        vehicle_miles_saved=solo - vm,
        passenger_miles=pm,
        occupancy=(pm / vm) if vm > 0 else 0.0,
        added_detour_minutes=detour,
        ride_time_minutes=tuple(rides),
        direct_minutes=tuple(directs),
        worst_ride_time_slack_minutes=0.0 if worst_slack is math.inf else worst_slack,
        window_slack_consumed_minutes=consumed,
        peak_floor_units=peak,
        floor_capacity=capacity,
        wheelchair_riders=wc,
        wheelchair_positions=profile.positions_on(certificate.vehicle),
        requires_accessible_vehicle=wc > 0,
        equipment_contention=(peak / capacity) if capacity else 0.0,
        overlapping_pairs=overlaps,
        shared_vehicle_miles=route_shared_vehicle_miles(instance, seq),
    )


# ==========================================================================
# Proposals. A scorer sees this and only this.
# ==========================================================================

@dataclass(frozen=True)
class ProposalView:
    """Everything a scorer is permitted to know about a candidate grouping.

    Deliberately incomplete, in the same way `online.OnlineView` is. There is no
    schedule here, no violation list, no certificate, and no field a feasibility
    verdict could be written into. A scorer cannot conclude that a group is
    feasible because it has no vocabulary in which to say so, and the graph will
    not admit a group on a score -- only on a certificate.

    The cheap geometry IS supplied, because ranking is exactly what a scorer is
    for and starving it would make the interface useless rather than safe.
    """

    instance_name: str
    request_ids: tuple[int, ...]
    vehicle: int
    vehicle_is_accessible: bool
    needs_wheelchair: tuple[bool, ...]
    pickup_xy: tuple[tuple[float, float], ...]
    dropoff_xy: tuple[tuple[float, float], ...]
    pickup_window: tuple[tuple[float, float], ...]
    dropoff_window: tuple[tuple[float, float], ...]
    direct_minutes: tuple[float, ...]
    max_ride_time: float
    vehicle_capacity: int
    floor_units: tuple[int, ...]

    @property
    def order(self) -> int:
        return len(self.request_ids)


ProposalScorer = Callable[[ProposalView], float]
"""Rank a candidate grouping. Higher means more promising, and means NOTHING
else. A scorer that returns +inf for an infeasible group changes only the order
in which the authority examines candidates."""


def _proposal_view(
    instance: DarpInstance, profile: AccessibilityProfile, ids: Sequence[int], vehicle: int
) -> ProposalView:
    P = [instance.nodes[instance.pickup_index(r)] for r in ids]
    D = [instance.nodes[instance.dropoff_index(r)] for r in ids]
    return ProposalView(
        instance_name=instance.name,
        request_ids=tuple(ids),
        vehicle=vehicle,
        vehicle_is_accessible=profile.is_accessible(vehicle),
        needs_wheelchair=tuple(profile.needs_wheelchair(r) for r in ids),
        pickup_xy=tuple((p.x, p.y) for p in P),
        dropoff_xy=tuple((d.x, d.y) for d in D),
        pickup_window=tuple((p.tw_start, p.tw_end) for p in P),
        dropoff_window=tuple((d.tw_start, d.tw_end) for d in D),
        direct_minutes=tuple(
            instance.dist(instance.pickup_index(r), instance.dropoff_index(r)) for r in ids
        ),
        max_ride_time=instance.max_ride_time,
        vehicle_capacity=instance.vehicle_capacity,
        floor_units=tuple(profile.floor_units(instance, r) for r in ids),
    )


def geometric_affinity(view: ProposalView) -> float:
    """A hand-written ranking heuristic. NOT a learned model, and nothing in this
    repository trains one.

    Prefers groups whose pickups are close, whose drop-offs are close, whose time
    windows overlap, and whose combined floor demand leaves room. It exists so the
    graph has a defensible default enumeration order and so the interface has a
    reference implementation -- a trained ranker replaces it by being passed as
    `scorer=`, and gains no authority whatsoever by being trained.
    """
    ids = view.request_ids
    if len(ids) < 2:
        return 0.0
    pd = dd = 0.0
    overlap = 0.0
    pairs = 0
    for i, j in itertools.combinations(range(len(ids)), 2):
        pd += math.dist(view.pickup_xy[i], view.pickup_xy[j])
        dd += math.dist(view.dropoff_xy[i], view.dropoff_xy[j])
        lo = max(view.pickup_window[i][0], view.pickup_window[j][0])
        hi = min(view.pickup_window[i][1], view.pickup_window[j][1])
        overlap += max(0.0, hi - lo)
        pairs += 1
    pd /= pairs
    dd /= pairs
    overlap /= pairs
    slack = view.vehicle_capacity - sum(view.floor_units)
    if slack < 0:
        return -math.inf  # cannot fit even if every rider boarded alone in turn
    scale = max(1e-9, sum(view.direct_minutes) / len(ids))
    return (overlap / (1.0 + view.max_ride_time)) - (pd + dd) / (2.0 * scale) + 0.05 * slack


# ==========================================================================
# The graph.
# ==========================================================================

@dataclass(frozen=True)
class CompatibilityEdge:
    """One certified sharing group. Order 2 is an edge; order >= 3 a hyperedge.

    The certificate is not optional and there is no "unverified edge" state --
    an edge in this graph MEANS a proof exists, and the type has no way to
    represent a group that was merely scored highly.
    """

    request_ids: tuple[int, ...]
    vehicle: int
    certificate: Certificate
    features: ShareFeatures
    proposal_score: float

    @property
    def order(self) -> int:
        return len(self.request_ids)

    def to_record(self) -> dict:
        return {
            "request_ids": list(self.request_ids),
            "order": self.order,
            "vehicle": self.vehicle,
            "proposal_score": round(self.proposal_score, 6),
            "certificate": self.certificate.to_record(),
            "features": self.features.to_record(),
        }


class ForgedCertificate(AssertionError):
    """A certificate offered to the graph did not survive re-checking.

    An `AssertionError` and not a soft rejection: the only ways to reach it are a
    forged witness or a genuine bug in the authority, and both mean the graph's
    core invariant -- every edge is a proof -- has already been broken.
    """


@dataclass(frozen=True)
class CompatibilityGraph:
    """Requests as nodes; certified sharing groups as edges and hyperedges.

    `proposals_scored` vs `edges + hyperedges` is the honest measure of how much
    the scorer's ranking mattered, and `rejections_by_checker` says which
    constraint did the rejecting. A graph in which the equipment checker never
    rejects anything is a graph built on a configuration where equipment
    contention is inert; `AccessibilityProfile.can_bind` is the guard against
    quoting such a run as evidence about accessibility.
    """

    instance_name: str
    profile: AccessibilityProfile
    nodes: tuple[int, ...]
    edges: tuple[CompatibilityEdge, ...]
    hyperedges: tuple[CompatibilityEdge, ...]
    max_group_size: int
    proposals_scored: int
    proposals_certified: int
    rejections_by_checker: tuple[tuple[str, int], ...]
    scorer_name: str
    truncated: bool
    equipment_layer_can_bind: bool
    version: str = COMPATIBILITY_VERSION

    @property
    def all_groups(self) -> tuple[CompatibilityEdge, ...]:
        return self.edges + self.hyperedges

    def neighbours(self, request: int) -> tuple[int, ...]:
        """Requests that can share with `request` PAIRWISE. Derived from edges
        only -- a hyperedge partner is not a pairwise neighbour unless the pair
        was itself certified, and conflating the two would let an unproven pair
        look proven."""
        out: set[int] = set()
        for e in self.edges:
            if request in e.request_ids:
                out.update(i for i in e.request_ids if i != request)
        return tuple(sorted(out))

    def edge_between(self, a: int, b: int) -> CompatibilityEdge | None:
        key = tuple(sorted((a, b)))
        return next((e for e in self.edges if e.request_ids == key), None)

    def groups_containing(self, request: int) -> tuple[CompatibilityEdge, ...]:
        return tuple(e for e in self.all_groups if request in e.request_ids)

    def isolated(self) -> tuple[int, ...]:
        """Requests with no certified sharing partner at all. The riders whose
        trip cannot be pooled however good the planner is -- worth naming, because
        an occupancy target that ignores them is a target that will be met by
        declining them."""
        paired = {r for e in self.all_groups for r in e.request_ids}
        return tuple(r for r in self.nodes if r not in paired)

    def to_record(self) -> dict:
        return {
            "instance": self.instance_name,
            "version": self.version,
            "nodes": len(self.nodes),
            "edges_order_2": len(self.edges),
            "hyperedges_order_3plus": len(self.hyperedges),
            "max_group_size": self.max_group_size,
            "proposals_scored": self.proposals_scored,
            "proposals_certified": self.proposals_certified,
            "rejections_by_checker": {k: v for k, v in self.rejections_by_checker},
            "scorer": self.scorer_name,
            "enumeration_truncated": self.truncated,
            "isolated_requests": list(self.isolated()),
            "equipment_layer_can_bind": self.equipment_layer_can_bind,
            "accessibility": self.profile.to_record(),
        }


def _representative_vehicle(profile: AccessibilityProfile, ids: Sequence[int]) -> int | None:
    """The lowest-indexed vehicle able to carry this group's equipment needs.

    Cordeau instances have a homogeneous fleet, so the only thing that
    distinguishes vehicles here is the accessibility we assigned. Certifying on a
    representative therefore answers "can this group share A vehicle" with one
    call instead of K, and the planner re-certifies against the ACTUAL vehicle and
    its actual existing riders before committing anything -- the graph's vehicle
    is a feasibility witness, never a dispatch decision.
    """
    needs = any(profile.needs_wheelchair(r) for r in ids)
    pool = sorted(profile.accessible_vehicles) if needs else sorted(range(profile.num_vehicles))
    return pool[0] if pool else None


def build_compatibility_graph(
    instance: DarpInstance,
    profile: AccessibilityProfile,
    *,
    scorer: ProposalScorer = geometric_affinity,
    scorer_name: str | None = None,
    max_group_size: int = 2,
    max_proposals: int | None = None,
    hyperedge_candidates: int = 400,
    verify_on_admission: bool = True,
    require_shared_ride: bool = True,
) -> CompatibilityGraph:
    """Build the compatibility graph for one instance under one profile.

    Order 2 is enumerated in full: every pair is scored, and every pair is offered
    to the authority. The scorer's ranking changes only the order in which they
    are examined, so at order 2 the graph does not depend on the scorer at all
    unless `max_proposals` truncates -- which is the strongest available statement
    that scoring carries no authority, and the suite tests exactly that.

    Order 3+ is where a scorer earns its keep: the candidate space is
    combinatorial, so the top `hyperedge_candidates` scored triples (extended from
    certified pairs) are what gets certified. That is a COMPLETENESS bound and it
    is recorded on the graph as `truncated`: a group absent from this graph was
    either rejected by a checker or never proposed, and the two are not the same.
    SOUNDNESS is unaffected -- everything present is proved.

    Sub-group closure is NOT assumed. A certified triple is not taken as evidence
    that its pairs are feasible, nor the reverse; each is certified on its own.
    """
    n = instance.num_requests
    nodes = tuple(range(1, n + 1))
    scored = 0
    certified = 0
    rejections: dict[str, int] = {_ROUTING_CHECKER: 0, _EQUIPMENT_CHECKER: 0, _SCHEDULER: 0}
    truncated = False

    def rank(groups: Iterable[tuple[int, ...]]) -> list[tuple[tuple[int, ...], int, float]]:
        """Score every candidate ONCE and order by descending score, ties broken
        by request ids so the order is total and reproducible. Scoring is the only
        thing the scorer does; nothing downstream reads the number again."""
        nonlocal scored
        out: list[tuple[tuple[int, ...], int, float]] = []
        for ids in groups:
            vehicle = _representative_vehicle(profile, ids)
            if vehicle is None:
                continue  # no vehicle in the fleet carries this group's equipment need
            out.append((ids, vehicle, float(scorer(_proposal_view(instance, profile, ids, vehicle)))))
            scored += 1
        out.sort(key=lambda t: (-t[2], t[0]))
        return out

    def offer(ids: tuple[int, ...], vehicle: int, score: float) -> CompatibilityEdge | None:
        nonlocal certified
        outcome = certify_group(
            instance, profile, ids, vehicle, require_shared_ride=require_shared_ride
        )
        if outcome.certificate is None:
            for who in outcome.rejected_by:
                rejections[who] = rejections.get(who, 0) + 1
            return None
        certified += 1
        cert = outcome.certificate
        if verify_on_admission:
            residual = cert.recheck(instance, profile)
            if residual:
                raise ForgedCertificate(
                    f"certificate for {ids} on vehicle {vehicle} did not survive re-checking: "
                    f"{residual[:3]}"
                )
        return CompatibilityEdge(
            request_ids=ids,
            vehicle=vehicle,
            certificate=cert,
            features=share_features(instance, profile, cert),
            proposal_score=score,
        )

    # --- order 2: every pair, scored then certified -------------------------
    ranked_pairs = rank(tuple(sorted(c)) for c in itertools.combinations(nodes, 2))
    if max_proposals is not None and len(ranked_pairs) > max_proposals:
        ranked_pairs = ranked_pairs[:max_proposals]
        truncated = True
    edges: list[CompatibilityEdge] = []
    for ids, vehicle, score in ranked_pairs:
        edge = offer(ids, vehicle, score)
        if edge is not None:
            edges.append(edge)
    edges.sort(key=lambda e: e.request_ids)

    # --- order 3+: the scorer proposes, the authority disposes ---------------
    hyper: list[CompatibilityEdge] = []
    if max_group_size >= 3:
        certified_pairs = {e.request_ids for e in edges}
        adjacency: dict[int, set[int]] = {r: set() for r in nodes}
        for a, b in certified_pairs:
            adjacency[a].add(b)
            adjacency[b].add(a)
        candidates: set[tuple[int, ...]] = set()
        for a, b in certified_pairs:
            for c in sorted(adjacency[a] | adjacency[b]):
                if c in (a, b):
                    continue
                candidates.add(tuple(sorted((a, b, c))))
        ranked = rank(sorted(candidates))
        if len(ranked) > hyperedge_candidates:
            ranked = ranked[:hyperedge_candidates]
            truncated = True
        for ids, vehicle, score in ranked:
            edge = offer(ids, vehicle, score)
            if edge is not None:
                hyper.append(edge)
        hyper.sort(key=lambda e: e.request_ids)

    return CompatibilityGraph(
        instance_name=instance.name,
        profile=profile,
        nodes=nodes,
        edges=tuple(edges),
        hyperedges=tuple(hyper),
        max_group_size=max_group_size,
        proposals_scored=scored,
        proposals_certified=certified,
        rejections_by_checker=tuple(sorted(rejections.items())),
        scorer_name=scorer_name or getattr(scorer, "__name__", "custom"),
        truncated=truncated,
        equipment_layer_can_bind=profile.can_bind(instance),
    )


def with_capacity_features(
    edge: CompatibilityEdge, *, cost: float, accessible_cost: float
) -> CompatibilityEdge:
    """Attach a future-capacity estimate to an edge, leaving the certificate and
    every exact feature untouched. Used by `packages.decide.capacity_value`; kept
    here so the dataclass stays frozen and the estimate can never overwrite a
    measured field."""
    return CompatibilityEdge(
        request_ids=edge.request_ids,
        vehicle=edge.vehicle,
        certificate=edge.certificate,
        features=replace(
            edge.features,
            future_capacity_cost=cost,
            future_accessible_capacity_cost=accessible_cost,
        ),
        proposal_score=edge.proposal_score,
    )
