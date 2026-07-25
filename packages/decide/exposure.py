"""Exposure measurement for online commitment decisions in commingled service.

WHAT THIS IS FOR, AND WHAT IT MUST NEVER BE USED FOR.

Commingling general-public and accessible demand-response trips on one fleet
makes the scheduling problem HARDER, not easier. Next-day service is generous in
one specific way: the scheduler sees every trip before it commits to any of them.
Same-day service removes that. You accept a general-public rider at nine in the
morning without knowing whether doing so costs a wheelchair user a trip at four
in the afternoon, and you cannot take the decision back. That is an exposure
question, and at present nobody can demonstrate afterwards that the trade was
made correctly. This module is an attempt to make it demonstrable.

**This measurement exists to show whether a commingling policy is quietly
shifting cost onto disabled riders, so that capacity can be RELEASED to them. It
is not, and must never be used as, a justification for serving fewer riders.
Restricting transit use is not the objective.** Nothing here recommends declining
a trip; the harness this builds on
(`packages.decide.online`) structurally refuses to run a policy that declines a
rider it could serve, so no number produced here can be quoted in support of
trip-by-trip capacity rationing. What varies between policies is WHERE a rider is
placed, never WHETHER they are served.

THREE THINGS ARE MEASURED.

1. THE COST OF NOT SEEING THE FUTURE. The same request set is run twice: once
   sequentially through `packages.decide.online`, where each commitment is made
   blind to later arrivals and cannot be revoked; once through
   `packages.decide.commingled.solve_commingled_offline`, a CP-SAT model that
   sees every request before deciding anything. Both search the identical
   pickup-time grid, so the difference between them is FORESIGHT and not
   discretization. That difference is the quantity nobody in the industry
   currently reports.

   The offline side is the yardstick because it is provable. It is optimal
   RELATIVE TO THE POLICY'S PICKUP-TIME GRID -- the same bounded claim ADR-0060
   makes when it says `certified_optimal` means optimal within the lattice
   resolution, never absolutely. Quoting the shortfall without that qualifier
   overstates it.

2. WHO BEARS IT. The shortfall is broken down by accessibility requirement, so
   that "we served 3% fewer trips overall" can be told apart from "we served 3%
   fewer trips and every one of them needed a wheelchair-accessible vehicle."
   The second sentence is the entire point. A single aggregate percentage is
   precisely the statistic under which the distributional harm hides.

3. WHICH CAPACITY WAS CONSUMED. For a request that was declined, `attribute_capacity`
   identifies which earlier commitments had taken the capacity that would have
   served it.

   THIS IS A CAPACITY ATTRIBUTION, NOT A CAUSAL PROOF, and the output is shaped
   to make that impossible to misread. A denial can have several sufficient
   causes: if there are three ways to have freed a seat, no one of the three
   caused the denial and naming a single culprit would be a fabrication. So the
   result is the SET of minimal blocking sets -- every minimal group of earlier
   commitments whose release would have made the trip servable. A single
   commitment is named only when it appears in every one of them, so that every
   route to serving the rider ran through it, and only when the enumeration was
   exhaustive enough to know that.

   Its scope is narrow and stated on the type: it holds every other commitment
   fixed. It does not re-run the policy, so it does not model what the scheduler
   would have done with the freed capacity, and it is not a counterfactual
   history. It answers "whose trip is sitting in the capacity this rider needed",
   which is the question an operator can actually act on.

WHAT IS DELIBERATELY NOT CLAIMED.

- Online stochastic scheduling is NOT solved here. There is no forecast, no
  arrival model, no acceptance threshold, no competitive ratio and no
  optimality claim of any kind for the online side. We do not believe the problem
  is solved and this module does not pretend otherwise. Measuring the gap is the
  contribution; closing it is not.
- No causal claim. See the attribution note above.
- No operational claim. Every instance this runs on is synthetic or academic and
  the accessibility labels on them are ASSIGNED by
  `packages.decide.commingled.derive_commingled_instance`, because the published
  benchmark files carry no accessibility attribute at all. Results support
  ALGORITHMIC claims only -- that the measurement works and discriminates between
  cohorts. They say nothing about the exposure any real agency's riders face, and
  no number from this module may be cited as operational evidence.
- Degradation is REPORTED but not ATTRIBUTED. Window deferral is described per
  cohort; only outright denials are traced back to the capacity they needed.
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass
from datetime import datetime

from packages.decide.commingled import (
    CommingledFleet,
    CommingledInstance,
    CommingledOutcome,
    has_placement,
    pool_only_relaxation,
    solve_commingled_offline,
)
from packages.decide.ir import DecisionProblem, RideRequest
from packages.decide.online import OnlineOutcome, OnlinePolicy, arrivals_from, run_online
from packages.decide.solver import _candidate_times

EXPOSURE_VERSION = "0.4.0"

WHEELCHAIR = "wheelchair-accessible-vehicle-required"
AMBULATORY = "no-accessibility-requirement"


# ==========================================================================
# Capacity attribution.
# ==========================================================================

@dataclass(frozen=True)
class CapacityAttribution:
    """Which earlier commitments consumed the capacity a declined request needed.

    NOT a causal proof. Read the fields in this order:

    - `servable_in_isolation` False means this trip could not have been served by
      an EMPTY fleet either -- no accessible vehicle on shift in its window, or a
      window nothing could reach. The denial then has nothing to do with
      commingling, and no attribution is made. Reporting one anyway would blame
      riders for a structural gap in the service.
    - `blocking_sets` are the MINIMAL groups of earlier commitments whose release
      would have made this trip servable. Several of them means several
      sufficient causes and no single culprit; that is the normal case and the
      output says so rather than picking one.
    - `necessary_commitments` are the commitments in EVERY minimal blocking set:
      every way of freeing capacity for this rider ran through them. This is the
      only field that names an individual trip, and it is empty unless
      `enumeration_complete` is True, because a partial search cannot establish
      "every way".
    - `participation` is the fraction of minimal blocking sets each commitment
      appears in. A descriptive share of the responsibility, not a probability
      and not a causal weight.
    - `enumeration_complete` False means the search was bounded (by
      `max_set_size` or the subset budget) and the sets found are a lower bound on
      what exists. Do not read absence of a blocking set as absence of blocking.

    SCOPE, stated on the type because it is the easiest thing to over-read: this
    holds every OTHER commitment exactly where it is. It does not re-run the
    policy on the freed capacity and does not model what the day would have looked
    like. It says whose trip is sitting in the capacity this rider needed.
    """

    request_id: str
    needs_wheelchair: bool
    sequence: int
    servable_in_isolation: bool
    contenders_examined: int
    blocking_sets: tuple[tuple[str, ...], ...]
    necessary_commitments: tuple[str, ...]
    participation: tuple[tuple[str, float], ...]
    enumeration_complete: bool
    max_set_size_searched: int
    subsets_tested: int
    detail: str

    @property
    def has_attribution(self) -> bool:
        return bool(self.blocking_sets)

    def to_record(self) -> dict:
        return {
            "request_id": self.request_id,
            "needs_wheelchair": self.needs_wheelchair,
            "arrival_sequence": self.sequence,
            "servable_in_isolation": self.servable_in_isolation,
            "contenders_examined": self.contenders_examined,
            "minimal_blocking_sets": [list(s) for s in self.blocking_sets],
            "necessary_commitments": list(self.necessary_commitments),
            "participation": {k: v for k, v in self.participation},
            "enumeration_complete": self.enumeration_complete,
            "max_set_size_searched": self.max_set_size_searched,
            "subsets_tested": self.subsets_tested,
            "detail": self.detail,
        }


def _request_span(problem: DecisionProblem, request: RideRequest) -> tuple[datetime, datetime] | None:
    """The widest interval this request could ever occupy a vehicle for, across
    every vehicle and every candidate pickup on the shared grid. A prior ride that
    does not overlap it cannot be holding capacity this request needed, so it is
    excluded from the search -- a sound prune, not a heuristic one."""
    lo: datetime | None = None
    hi: datetime | None = None
    for veh in problem.vehicles:
        times = _candidate_times(request, veh, problem.policy.time_granularity_minutes)
        if not times:
            continue
        first, last = times[0], times[-1] + request.nominal_ride
        lo = first if lo is None or first < lo else lo
        hi = last if hi is None or last > hi else hi
    return None if lo is None else (lo, hi)


def _usable_vehicle_ids(problem: DecisionProblem, request: RideRequest) -> set[str]:
    """Vehicles this request could ride at all, ignoring contention."""
    return {
        str(v.vehicle_id)
        for v in problem.vehicles
        if _candidate_times(request, v, problem.policy.time_granularity_minutes)
    }


def attribute_capacity(
    problem: DecisionProblem,
    fleet: CommingledFleet,
    outcome: OnlineOutcome,
    request_id: str,
    *,
    max_set_size: int = 3,
    max_subsets: int = 20_000,
) -> CapacityAttribution:
    """Which earlier commitments consumed the capacity that would have served the
    declined request `request_id`.

    Enumerates subsets of the CONTENDING earlier commitments by increasing size
    and keeps every minimal one whose release would have made the trip servable.
    Minimality is checked against the sets already found, which is exact because
    the search is breadth-first in set size.

    `max_set_size` and `max_subsets` bound the work. When either bites,
    `enumeration_complete` is False and the result is explicitly a lower bound --
    the module never lets a truncated search be read as a complete one.
    """
    request = next(r for r in problem.requests if str(r.request_id) == str(request_id))
    commitment = outcome.commitment_for(str(request_id))
    if commitment.accepted:
        raise ValueError(f"request {request_id} was accepted; there is nothing to attribute")

    if not has_placement(problem, fleet, (), request):
        return CapacityAttribution(
            request_id=str(request_id),
            needs_wheelchair=request.needs_wheelchair,
            sequence=commitment.sequence,
            servable_in_isolation=False,
            contenders_examined=0,
            blocking_sets=(),
            necessary_commitments=(),
            participation=(),
            enumeration_complete=True,
            max_set_size_searched=0,
            subsets_tested=0,
            detail=(
                "this trip could not have been served on an EMPTY fleet either -- no vehicle on "
                "shift can reach its window, or none carries the accessibility it needs. The denial "
                "is a structural gap in the service, not a commingling effect, and attributing it "
                "to another rider's trip would be false."
            ),
        )

    prior = outcome.accepted_before(commitment.sequence)
    span = _request_span(problem, request)
    usable = _usable_vehicle_ids(problem, request)
    contenders = [
        a for a in prior
        if a.placement.vehicle_id in usable
        and span is not None
        and a.placement.pickup_time < span[1]
        and a.placement.dropoff_time > span[0]
    ]
    fixed = [a for a in prior if a not in contenders]
    ids = [a.request_id for a in contenders]
    index = {a.request_id: a for a in contenders}

    blocking: list[frozenset[str]] = []
    tested = 0
    budget_hit = False
    searched_to = 0
    limit = min(max_set_size, len(ids))
    for k in range(1, limit + 1):
        searched_to = k
        for combo in itertools.combinations(ids, k):
            if tested >= max_subsets:
                budget_hit = True
                break
            s = frozenset(combo)
            if any(m <= s for m in blocking):
                continue  # a proper subset already suffices, so this is not minimal
            tested += 1
            kept = fixed + [index[i] for i in ids if i not in s]
            if has_placement(problem, fleet, kept, request):
                blocking.append(s)
        if budget_hit:
            break

    complete = not budget_hit and max_set_size >= len(ids)
    if blocking:
        counts = {i: sum(1 for s in blocking if i in s) for i in ids}
        participation = tuple(
            sorted(
                ((i, round(c / len(blocking), 4)) for i, c in counts.items() if c),
                key=lambda kv: (-kv[1], kv[0]),
            )
        )
        # A commitment named individually only if EVERY minimal release includes
        # it -- and only if we searched exhaustively enough to say "every".
        necessary = tuple(sorted(i for i in ids if all(i in s for s in blocking))) if complete else ()
        detail = (
            f"{len(blocking)} minimal blocking set(s) over {len(contenders)} contending earlier "
            f"commitments. "
            + (
                f"{len(necessary)} commitment(s) appear in all of them."
                if complete
                else "Search was BOUNDED, so these sets are a lower bound and no commitment is "
                     "named as necessary."
            )
            + " Releasing a blocking set would have freed the capacity; it is not a claim about "
              "what the scheduler would then have done."
        )
    else:
        participation = ()
        necessary = ()
        detail = (
            f"no release of up to {searched_to} earlier commitment(s) among {len(contenders)} "
            f"contenders would have served this trip"
            + (
                ". The search was exhaustive, so the capacity shortfall is deeper than any "
                "single group of earlier trades."
                if complete
                else ". The search was BOUNDED; a larger release may exist and this is not "
                     "evidence that none does."
            )
        )

    return CapacityAttribution(
        request_id=str(request_id),
        needs_wheelchair=request.needs_wheelchair,
        sequence=commitment.sequence,
        servable_in_isolation=True,
        contenders_examined=len(contenders),
        blocking_sets=tuple(tuple(sorted(s)) for s in blocking),
        necessary_commitments=necessary,
        participation=participation,
        enumeration_complete=complete,
        max_set_size_searched=searched_to,
        subsets_tested=tested,
        detail=detail,
    )


# ==========================================================================
# The distributional report.
# ==========================================================================

@dataclass(frozen=True)
class CohortExposure:
    """One accessibility cohort's share of the demand and of the shortfall.

    `share_of_shortfall` against `share_of_demand` is the comparison the whole
    packet exists for. Equal shares mean the cost of not seeing the future landed
    proportionately. A share of shortfall above a share of demand means the online
    commitment order is shifting cost onto this cohort.
    """

    cohort: str
    demand: int
    served_online: int
    served_offline: int
    shortfall: int
    share_of_demand: float
    share_of_shortfall: float | None
    mean_window_deferral_online_minutes: float | None
    mean_window_deferral_offline_minutes: float | None

    def to_record(self) -> dict:
        return {
            "cohort": self.cohort,
            "demand": self.demand,
            "served_online": self.served_online,
            "served_offline": self.served_offline,
            "shortfall": self.shortfall,
            "share_of_demand": self.share_of_demand,
            "share_of_shortfall": self.share_of_shortfall,
            "mean_window_deferral_online_minutes": self.mean_window_deferral_online_minutes,
            "mean_window_deferral_offline_minutes": self.mean_window_deferral_offline_minutes,
        }


@dataclass(frozen=True)
class ExposureReport:
    """The online-vs-offline gap on one instance under one policy, with the
    distributional breakdown and the attributions behind it.

    `offline_proven_optimal` is load-bearing. When it is True the shortfall is the
    exact cost of not seeing the future, relative to the pickup-time grid both
    sides search. When it is False the offline side is an incumbent, so the true
    optimum is at least as good and the shortfall reported is a LOWER BOUND -- the
    direction it is safe to be wrong in, but it must be read as one.
    """

    instance: str
    policy: str
    seed: int
    requests: int
    served_online: int
    served_offline: int
    shortfall: int
    objective_online: float
    objective_offline: float | None
    offline_proven_optimal: bool
    offline_status: str
    floor_binds: bool
    cohorts: tuple[CohortExposure, ...]
    attributions: tuple[CapacityAttribution, ...]
    concentration: float | None
    pool_only_served: int | None
    pool_only_proven: bool
    wall_time_s: float
    exposure_version: str = EXPOSURE_VERSION

    @property
    def accessible_cohort(self) -> CohortExposure:
        return next(c for c in self.cohorts if c.cohort == WHEELCHAIR)

    def headline(self) -> str:
        """The one sentence the packet is about, or an honest refusal to say it."""
        if self.shortfall == 0:
            return (
                f"{self.instance}/{self.policy}: the online run matched the offline optimum "
                f"({self.served_online}/{self.requests} trips). No cost of foresight to distribute."
            )
        wc = self.accessible_cohort
        qualifier = "" if self.offline_proven_optimal else " (offline side unproven; shortfall is a LOWER bound)"
        if wc.shortfall == self.shortfall:
            return (
                f"{self.instance}/{self.policy}: served {self.shortfall} fewer trips than the "
                f"offline optimum -- and EVERY ONE of them needed a wheelchair-accessible "
                f"vehicle{qualifier}."
            )
        return (
            f"{self.instance}/{self.policy}: served {self.shortfall} fewer trips than the offline "
            f"optimum; {wc.shortfall} of them needed a wheelchair-accessible vehicle "
            f"({wc.share_of_shortfall:.0%} of the shortfall against {wc.share_of_demand:.0%} of "
            f"demand){qualifier}."
        )

    def to_record(self) -> dict:
        return {
            "instance": self.instance,
            "policy": self.policy,
            "seed": self.seed,
            "requests": self.requests,
            "served_online": self.served_online,
            "served_offline": self.served_offline,
            "shortfall": self.shortfall,
            "shortfall_pct_of_demand": round(100.0 * self.shortfall / self.requests, 4) if self.requests else None,
            "objective_online": self.objective_online,
            "objective_offline": self.objective_offline,
            "offline_proven_optimal": self.offline_proven_optimal,
            "offline_status": self.offline_status,
            "floor_constraint_binds": self.floor_binds,
            "concentration_ratio": self.concentration,
            "pool_only_relaxation_served": self.pool_only_served,
            "pool_only_relaxation_proven": self.pool_only_proven,
            "cohorts": [c.to_record() for c in self.cohorts],
            "attributions": [a.to_record() for a in self.attributions],
            "wall_time_s": self.wall_time_s,
            "exposure_version": self.exposure_version,
            "headline": self.headline(),
        }


def _deferral_minutes(problem: DecisionProblem, solution, cohort_wheelchair: bool) -> float | None:
    """Mean minutes a served rider's pickup sits after the start of their window.

    Descriptive only. It is reported because a trip pushed to the far end of its
    window is a degraded trip and an aggregate served-count hides that, but it is
    NOT attributed to any earlier commitment -- see the module docstring.
    """
    by_id = {str(r.request_id): r for r in problem.requests}
    vals = [
        (a.pickup_time - by_id[str(a.request_id)].pickup_window_start).total_seconds() / 60.0
        for a in solution.assignments
        if by_id[str(a.request_id)].needs_wheelchair is cohort_wheelchair
    ]
    return round(sum(vals) / len(vals), 3) if vals else None


def measure_exposure(
    instance: CommingledInstance,
    policy: OnlinePolicy,
    *,
    policy_name: str,
    seed: int = 0,
    offline: CommingledOutcome | None = None,
    max_deterministic_time: float | None = 60.0,
    attribute: bool = True,
    max_set_size: int = 3,
    include_pool_only_check: bool = True,
) -> ExposureReport:
    """Run one instance online and offline and report the gap, who bore it, and
    which capacity the denied trips needed.

    `offline` may be passed in when several policies are measured against the same
    instance -- the offline optimum does not depend on the online policy, and
    re-solving it would be both slow and a chance for the two runs to disagree.
    """
    t0 = time.perf_counter()
    problem, fleet = instance.problem, instance.fleet
    arrivals = arrivals_from(problem, instance.booked_at)
    online = run_online(problem, fleet, arrivals, policy, policy_name=policy_name)

    if offline is None:
        offline = solve_commingled_offline(
            problem, fleet, seed=seed, max_deterministic_time=max_deterministic_time
        )

    pool_served: int | None = None
    pool_proven = False
    if include_pool_only_check:
        _obj, pool_served, pool_proven = pool_only_relaxation(
            problem, seed=seed, max_deterministic_time=max_deterministic_time
        )
        # The pool-only problem drops the floor constraint, so it is a relaxation:
        # its optimum cannot serve FEWER trips than the constrained optimum. A
        # violation means one of the two models is wrong, and a wrong model here
        # would corrupt every number in the report.
        if pool_proven and offline.proven_optimal and pool_served < offline.served:
            raise AssertionError(
                f"{instance.provenance.source}: the pool-only RELAXATION served {pool_served} "
                f"trips but the constrained commingled optimum served {offline.served}. A "
                f"relaxation cannot do worse; one of the two CP-SAT models is wrong."
            )

    online_ids = set(online.served_ids)
    offline_ids = set(offline.served_ids)
    total_shortfall = len(offline_ids) - len(online_ids)

    cohorts: list[CohortExposure] = []
    for name, needs_wc in ((WHEELCHAIR, True), (AMBULATORY, False)):
        members = [str(r.request_id) for r in problem.requests if r.needs_wheelchair is needs_wc]
        on = len([m for m in members if m in online_ids])
        off = len([m for m in members if m in offline_ids])
        short = off - on
        cohorts.append(
            CohortExposure(
                cohort=name,
                demand=len(members),
                served_online=on,
                served_offline=off,
                shortfall=short,
                share_of_demand=round(len(members) / len(problem.requests), 4) if problem.requests else 0.0,
                share_of_shortfall=(round(short / total_shortfall, 4) if total_shortfall > 0 else None),
                mean_window_deferral_online_minutes=_deferral_minutes(problem, online.solution, needs_wc),
                mean_window_deferral_offline_minutes=_deferral_minutes(problem, offline.solution, needs_wc),
            )
        )

    wc = next(c for c in cohorts if c.cohort == WHEELCHAIR)
    # >1 means the accessible cohort absorbed more of the shortfall than its share
    # of demand. Undefined (None) when there is no shortfall or no accessible
    # demand -- reporting 0 or 1 there would invent a finding.
    concentration = (
        round(wc.share_of_shortfall / wc.share_of_demand, 4)
        if (total_shortfall > 0 and wc.share_of_demand > 0 and wc.share_of_shortfall is not None)
        else None
    )

    attributions: tuple[CapacityAttribution, ...] = ()
    if attribute:
        attributions = tuple(
            attribute_capacity(problem, fleet, online, rid, max_set_size=max_set_size)
            for rid in online.declined_ids
        )

    return ExposureReport(
        instance=instance.provenance.source,
        policy=policy_name,
        seed=seed,
        requests=len(problem.requests),
        served_online=len(online_ids),
        served_offline=len(offline_ids),
        shortfall=total_shortfall,
        objective_online=online.objective,
        objective_offline=offline.objective,
        offline_proven_optimal=offline.proven_optimal,
        offline_status=offline.raw_status,
        floor_binds=fleet.binds_anywhere(problem),
        cohorts=tuple(cohorts),
        attributions=attributions,
        concentration=concentration,
        pool_only_served=pool_served,
        pool_only_proven=pool_proven,
        wall_time_s=round(time.perf_counter() - t0, 3),
    )
