"""Online (sequential) commitment for commingled demand-response.

Everything else in `packages.decide` is OFFLINE. `solver.solve`, `cpsat`,
`portfolio`, `commingled.solve_commingled_offline` all receive a
`DecisionProblem` containing every request and decide about all of them at once,
with each request's existence, window and mobility need known before any of them
is committed to. That is a fair model of NEXT-DAY service: the booking window
closes, and only then does the scheduler build a plan.

Same-day service removes exactly that. Requests arrive over the operating day.
Each accept or decline is made knowing only what has already arrived, and once
made it cannot be taken back -- a rider told "yes, 09:10" has arranged their day
around it. So the scheduler accepts a general-public rider at nine in the morning
without knowing whether doing so costs a wheelchair user a trip at four in the
afternoon. That is not an efficiency question. It is an EXPOSURE question, and
this module is the harness that makes it measurable.

THREE PROPERTIES THE HARNESS ENFORCES STRUCTURALLY. Each is enforced by the
harness rather than left to a policy's good behaviour, because a policy is
ordinary Python and a convention is not a guarantee.

1. NO LOOKAHEAD. A policy is handed an `OnlineView` and nothing else. The view
   carries the fleet, the request now arriving, the commitments already made, and
   the placements still available. It does not carry -- and the harness never
   computes -- anything about arrivals that have not happened yet. The observable
   consequence is PREFIX DETERMINISM: two arrival sequences sharing a common
   prefix produce identical commitments on that prefix. That is the testable form
   of "cannot see the future", and the conformance suite tests it directly.

2. IRREVOCABILITY. Commitments are append-only and `AcceptedRide` is frozen. A
   policy chooses only from the placements the harness computed for the request
   in front of it; it has no way to express "move the 09:10 rider". After each
   step the harness re-verifies that the committed prefix is unchanged and raises
   `IrrevocabilityViolation` if it is not.

3. IT WILL NOT RUN A RATIONING POLICY. If a policy declines a request for which a
   feasible placement existed, the harness raises `RationingRefused` and the run
   produces no result at all.

   That is a deliberate, load-bearing design choice and not a safety rail bolted
   on afterwards. The purpose of this measurement is to show whether a commingling
   policy quietly shifts cost onto disabled riders, so that capacity can be
   RELEASED to them. Restricting transit use is not the objective. A harness that
   could host a policy declining servable riders would produce numbers that could
   be quoted in support of trip-by-trip capacity rationing, and no such number can
   be produced here: every policy in this module serves every rider it possibly
   can, and the only thing that varies is WHERE it puts them.

   The two policies shipped here differ only in placement. `first_fit` takes the
   first available (vehicle, time). `preserve_accessible_capacity` prefers to put
   an ambulatory rider somewhere that leaves the fleet's scarce wheelchair-capable
   floor free -- serving the same rider, on a different seat. Any difference in
   outcome between them is capacity released, not capacity withheld.

WHAT THIS MODULE DOES NOT CLAIM. It does not solve online stochastic scheduling.
It has no demand forecast, no arrival model, no acceptance threshold, no
competitive-ratio argument, and it makes no claim of optimality of any kind. The
online problem is not solved here and, as far as we know, is not solved anywhere.
Measuring what not seeing the future costs is the contribution; closing that gap
is not, and a policy in this file that beat another one on an instance is not
evidence that it would on any other.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Sequence

from packages.canonical.vocab import ReasonCode, ScheduleRunStatus
from packages.decide.commingled import (
    AcceptedRide,
    CommingledFleet,
    Placement,
    check_commingled,
    commingled_objective,
    feasible_placements,
)
from packages.decide.ir import (
    Assignment,
    DecisionProblem,
    DecisionSolution,
    DecisionVehicle,
    Denial,
    RideRequest,
)
from packages.decide.solver import _static_reasons

ONLINE_HARNESS_NAME = "milexium-decide-online"
ONLINE_HARNESS_VERSION = "0.4.0"


class RationingRefused(AssertionError):
    """A policy declined a request it could have served.

    Raised, never recorded. See property 3 in the module docstring: this harness
    exists to show where capacity should be released, and it will not produce a
    measurement that a rationing policy could be read into.
    """


class IrrevocabilityViolation(AssertionError):
    """An earlier commitment changed after it was made.

    Always a bug in the harness (a policy has no way to cause it), and the one
    bug that would invalidate every number this package produces -- the online
    run would silently have become an offline re-plan.
    """


class InvalidPlacement(ValueError):
    """A policy returned a placement the harness did not offer it. A policy may
    only choose among placements the harness computed; inventing one would bypass
    both capacity gates."""


# ==========================================================================
# What arrives, what gets committed, what the policy is allowed to see.
# ==========================================================================

@dataclass(frozen=True)
class Arrival:
    """One request reaching the scheduler at a concrete instant."""

    request: RideRequest
    booked_at: datetime


@dataclass(frozen=True)
class Commitment:
    """One irrevocable accept or decline, in the order it was made.

    `sequence` is the position in the arrival stream. `alternatives_considered`
    records how much room the policy actually had -- a request accepted with one
    available placement is a different fact from one accepted with forty, and the
    capacity attribution reads it.
    """

    sequence: int
    request_id: str
    needs_wheelchair: bool
    accepted: bool
    decided_at: datetime
    placement: Placement | None = None
    alternatives_considered: int = 0
    reason_codes: tuple[ReasonCode, ...] = ()

    def to_record(self) -> dict:
        return {
            "sequence": self.sequence,
            "request_id": self.request_id,
            "needs_wheelchair": self.needs_wheelchair,
            "accepted": self.accepted,
            "decided_at": self.decided_at.isoformat(),
            "vehicle_id": self.placement.vehicle_id if self.placement else None,
            "pickup_time": self.placement.pickup_time.isoformat() if self.placement else None,
            "alternatives_considered": self.alternatives_considered,
            "reason_codes": [c.value for c in self.reason_codes],
        }


@dataclass(frozen=True)
class OnlineView:
    """Everything a policy is permitted to know at one decision point.

    Deliberately incomplete. There is no field for future arrivals, no demand
    forecast, and no count of how many requests are still to come -- because a
    same-day scheduler does not have any of those, and a policy that could read
    them would make the measured gap smaller than the real one for the wrong
    reason.
    """

    problem: DecisionProblem
    fleet: CommingledFleet
    request: RideRequest
    now: datetime
    sequence: int
    accepted: tuple[AcceptedRide, ...]
    options: tuple[Placement, ...]

    def vehicle(self, vehicle_id: str) -> DecisionVehicle:
        return next(v for v in self.problem.vehicles if str(v.vehicle_id) == vehicle_id)

    def accessible_vehicle_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(str(v.vehicle_id) for v in self.problem.vehicles if v.capacity_wheelchair >= 1)
        )


# A policy: given the view, pick one of `view.options`, or None only when there
# are none. Returning None while options exist is `RationingRefused`.
OnlinePolicy = Callable[[OnlineView], Placement | None]


# ==========================================================================
# Policies. Both serve every rider they can; they differ only in placement.
# ==========================================================================

def first_fit(view: OnlineView) -> Placement | None:
    """Take the first available (vehicle, pickup) in the harness's deterministic
    order. The natural baseline for a service that does not ration: say yes, put
    them wherever they fit, do not think about it.

    It is a baseline precisely because it is what an operator does when nobody has
    told them the placement matters. Its exposure number is the one to beat."""
    return view.options[0] if view.options else None


def preserve_accessible_capacity(view: OnlineView) -> Placement | None:
    """Serve this rider, on the seat that costs the fleet the least accessible
    capacity.

    An ambulatory rider is placed, in preference order, on a vehicle with no
    wheelchair position at all; failing that, on the accessible vehicle where
    their trip leaves the most contiguous floor free. A wheelchair rider is placed
    on whichever accessible vehicle can take them. Nobody is ever declined who
    could be served -- the rider gets the same trip either way. This releases
    capacity; it does not withhold any.

    It is a placement heuristic and nothing more. It carries no proof, no bound,
    and no guarantee that it helps on any instance it has not been run on.
    """
    if not view.options:
        return None
    accessible = set(view.accessible_vehicle_ids())
    needs_wc = view.request.needs_wheelchair

    def cost(p: Placement) -> tuple:
        on_accessible = p.vehicle_id in accessible
        if needs_wc:
            # A wheelchair rider must be on an accessible vehicle anyway; prefer
            # the earliest pickup so the floor is freed again sooner.
            return (0, p.pickup_time, p.vehicle_id)
        # An ambulatory rider: keep off the accessible vehicles where possible,
        # then prefer the placement occupying the least of the day still to come.
        return (1 if on_accessible else 0, p.pickup_time, p.vehicle_id)

    return min(view.options, key=cost)


POLICIES: dict[str, OnlinePolicy] = {
    "first-fit": first_fit,
    "preserve-accessible-capacity": preserve_accessible_capacity,
}


# ==========================================================================
# The run.
# ==========================================================================

@dataclass(frozen=True)
class OnlineOutcome:
    """What a sequential run produced.

    `solution` is a `DecisionSolution` in exactly the same shape every offline
    backend returns, so the independent checkers judge it on identical terms. Its
    status is FEASIBLE and never OPTIMAL: an online run proves nothing about what
    was achievable, which is the entire reason the offline optimum is computed
    separately.
    """

    policy_name: str
    commitments: tuple[Commitment, ...]
    accepted: tuple[AcceptedRide, ...]
    solution: DecisionSolution
    objective: float
    wall_time_s: float

    @property
    def served_ids(self) -> tuple[str, ...]:
        return tuple(sorted(a.request_id for a in self.accepted))

    @property
    def declined_ids(self) -> tuple[str, ...]:
        return tuple(sorted(c.request_id for c in self.commitments if not c.accepted))

    def commitment_for(self, request_id: str) -> Commitment:
        return next(c for c in self.commitments if c.request_id == str(request_id))

    def accepted_before(self, sequence: int) -> tuple[AcceptedRide, ...]:
        """The rides already committed to when the request at `sequence` arrived.
        This is the set the capacity attribution interrogates."""
        by_seq = {c.request_id: c.sequence for c in self.commitments}
        return tuple(a for a in self.accepted if by_seq[a.request_id] < sequence)

    def to_record(self) -> dict:
        return {
            "policy": self.policy_name,
            "served": len(self.accepted),
            "declined": len(self.declined_ids),
            "objective": self.objective,
            "wall_time_s": self.wall_time_s,
            "commitments": [c.to_record() for c in self.commitments],
        }


def arrivals_from(problem: DecisionProblem, booked_at: Sequence[tuple[str, datetime]]) -> tuple[Arrival, ...]:
    """Order the problem's requests by booking instant, ties broken by request id.

    Note what this makes explicit: the arrival ORDER is an input to the
    measurement, not a property of the instance. It is the one thing the operator
    does not control and cannot plan around, so an exposure number from a single
    order is an anecdote -- sweep it.
    """
    booking = dict((str(k), v) for k, v in booked_at)
    missing = [str(r.request_id) for r in problem.requests if str(r.request_id) not in booking]
    if missing:
        raise ValueError(f"no booking instant for requests {missing[:3]}")
    ordered = sorted(problem.requests, key=lambda r: (booking[str(r.request_id)], str(r.request_id)))
    return tuple(Arrival(request=r, booked_at=booking[str(r.request_id)]) for r in ordered)


def run_online(
    problem: DecisionProblem,
    fleet: CommingledFleet,
    arrivals: Sequence[Arrival],
    policy: OnlinePolicy,
    *,
    policy_name: str = "custom",
) -> OnlineOutcome:
    """Play the arrival stream through `policy`, one irrevocable decision at a time.

    Raises rather than reports on every way the run could stop being an online
    run: `RationingRefused` (declined a servable rider), `InvalidPlacement` (chose
    something not offered), `IrrevocabilityViolation` (an earlier commitment
    moved). None of the three is a condition to recover from -- each would mean
    the number produced was measuring something other than what it says.
    """
    known = {str(r.request_id) for r in problem.requests}
    seen: set[str] = set()
    for a in arrivals:
        rid = str(a.request.request_id)
        if rid not in known:
            raise ValueError(f"arrival {rid} is not one of the problem's requests")
        if rid in seen:
            raise ValueError(f"request {rid} arrives twice; one request is one commitment")
        seen.add(rid)

    t0 = time.perf_counter()
    accepted: list[AcceptedRide] = []
    commitments: list[Commitment] = []

    for seq, arrival in enumerate(arrivals):
        req = arrival.request
        frozen_prefix = tuple(accepted)
        options = feasible_placements(problem, fleet, frozen_prefix, req)
        view = OnlineView(
            problem=problem,
            fleet=fleet,
            request=req,
            now=arrival.booked_at,
            sequence=seq,
            accepted=frozen_prefix,
            options=options,
        )
        choice = policy(view)

        if choice is None:
            if options:
                raise RationingRefused(
                    f"policy {policy_name!r} declined request {req.request_id} at arrival {seq} "
                    f"although {len(options)} feasible placements existed. This harness does not "
                    f"run policies that decline riders they could serve -- see the module docstring."
                )
            commitments.append(
                Commitment(
                    sequence=seq,
                    request_id=str(req.request_id),
                    needs_wheelchair=req.needs_wheelchair,
                    accepted=False,
                    decided_at=arrival.booked_at,
                    alternatives_considered=0,
                    reason_codes=_static_reasons(req, problem),
                )
            )
        else:
            if choice not in options:
                raise InvalidPlacement(
                    f"policy {policy_name!r} returned a placement the harness did not offer for "
                    f"request {req.request_id}: {choice}"
                )
            accepted.append(
                AcceptedRide(
                    request_id=str(req.request_id),
                    placement=choice,
                    needs_wheelchair=req.needs_wheelchair,
                    party_size=req.party_size,
                )
            )
            commitments.append(
                Commitment(
                    sequence=seq,
                    request_id=str(req.request_id),
                    needs_wheelchair=req.needs_wheelchair,
                    accepted=True,
                    decided_at=arrival.booked_at,
                    placement=choice,
                    alternatives_considered=len(options),
                )
            )

        # PROPERTY 2, checked rather than assumed: nothing decided earlier moved.
        if tuple(accepted)[: len(frozen_prefix)] != frozen_prefix:
            raise IrrevocabilityViolation(
                f"the committed prefix changed while deciding arrival {seq}; this run is an "
                f"offline re-plan wearing an online harness's name"
            )

    solution = _solution_from(problem, accepted, commitments)
    violations = check_commingled(problem, fleet, solution)
    if violations:
        raise AssertionError(
            f"the online run produced a plan the independent checkers reject: {violations[:3]}"
        )
    objective = commingled_objective(problem, [a.request_id for a in accepted])
    return OnlineOutcome(
        policy_name=policy_name,
        commitments=tuple(commitments),
        accepted=tuple(accepted),
        solution=solution,
        objective=objective,
        wall_time_s=round(time.perf_counter() - t0, 4),
    )


def _solution_from(
    problem: DecisionProblem,
    accepted: Sequence[AcceptedRide],
    commitments: Sequence[Commitment],
) -> DecisionSolution:
    """Project the commitment log onto the IR's solution type.

    Every assignment comes from the placement recorded AT THE MOMENT OF
    COMMITMENT. Nothing is recomputed here -- recomputation is exactly how an
    online result would quietly become an offline one, and the conformance suite
    pins assignment-equals-commitment for that reason.
    """
    by_id = {str(r.request_id): r for r in problem.requests}
    vehicles = {str(v.vehicle_id): v for v in problem.vehicles}
    assignments = tuple(
        Assignment(
            request_id=by_id[a.request_id].request_id,
            vehicle_id=vehicles[a.placement.vehicle_id].vehicle_id,
            pickup_time=a.placement.pickup_time,
            dropoff_time=a.placement.dropoff_time,
        )
        for a in sorted(accepted, key=lambda a: a.request_id)
    )
    unserved = tuple(
        Denial(request_id=by_id[c.request_id].request_id, reason_codes=c.reason_codes)
        for c in sorted(commitments, key=lambda c: c.request_id)
        if not c.accepted
    )
    # FEASIBLE, never OPTIMAL. A sequential run proves nothing about what was
    # reachable; that is the offline optimum's job and the reason it is computed
    # separately rather than inferred from this.
    return DecisionSolution(
        status=ScheduleRunStatus.FEASIBLE,
        assignments=assignments,
        unserved=unserved,
        objective_value=None,
        bound=None,
        gap=None,
        seed=0,
        solver_name=ONLINE_HARNESS_NAME,
        solver_version=ONLINE_HARNESS_VERSION,
    )
