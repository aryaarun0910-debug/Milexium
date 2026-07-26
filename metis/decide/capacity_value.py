"""Future capacity value: what committing a vehicle NOW costs a rider LATER.

THE GAP THIS CLOSES. `metis.decide.exposure` (ADR-0065) measures, after the
day is over, that an online scheduler served fewer trips than an offline optimum
and which cohort absorbed the shortfall; `attribute_capacity` then names the
earlier commitments that consumed the capacity a denied rider needed. Both are
retrospective by construction -- they need the denial to have already happened.
That makes them an excellent audit and no help at all at 09:00, which is when the
decision that causes the 16:00 denial is actually taken.

This module answers the same question at decision time and in the other
direction: **if this accessible vehicle takes request A now, which likely future
requests become infeasible?** It is deliberately not a forecast of aggregate
vehicle-hours. An aggregate cannot be acted on by a dispatcher and cannot be
stratified by who bears it; the count of specific, plausible future trips a
commitment forecloses can be both.

**RELEASING CAPACITY, NEVER RATIONING IT.** Read this before using any number
here. A foreclosure estimate is an argument for putting a rider on a DIFFERENT
vehicle, never for declining one. `metis.decide.pooling`, the only planner
that consumes this module, reuses the online harness's structural refusal to run
a policy that declines a rider it could serve -- so no value computed here can
end up justifying a rider being turned away. The quantity is an input to WHERE,
not to WHETHER.

HOW IT IS COMPUTED, AND WHY THE FEASIBILITY IS REAL EVEN THOUGH THE DEMAND IS NOT.

    reach(state)        = how many sampled future requests admit a CERTIFIED
                          insertion into the fleet as it currently stands
    foreclosed(a -> b)  = reach(a) - reach(b)

`reach` calls `metis.decide.compatibility.admits_insertion`, which is the same
authority everything else in this packet goes through: an exact schedule offered
to `feasibility.check_darp_feasibility` and to the equipment checker, both of
which must return nothing. So the FEASIBILITY half of the estimate is not
learned, not approximated and not scored -- a scenario trip counts as reachable
only when a schedule exists that two independent checkers accept. What is
uncertain is only WHICH trips will ask.

THE PRIOR IS AN ASSUMPTION AND ITS MAGNITUDE FLOWS INTO EVERY NUMBER HERE.
`prior_from_observed` builds the scenario distribution by resampling requests the
scheduler has ALREADY SEEN and displacing them in space and time. That is a
placeholder, not a demand model: it says "the rest of the day looks like the part
we have seen, moved around". Three consequences, stated rather than buried:

- The absolute foreclosure counts are only as meaningful as that assumption.
  Treat them as a comparable ordering over placements, not as a prediction of how
  many trips will really be lost.
- Program E's forecasting stack is NOT wired in here and this module does not
  import it. That is a real limitation and also a deliberate boundary -- a
  learned arrival model belongs behind this interface, and would change the
  scenarios without touching the feasibility path or gaining any authority over
  it.
- Sampling noise is REPORTED. `CapacityValue` carries the number of independent
  draws and the standard error of the mean across them. A foreclosure difference
  smaller than its standard error is not a finding, and the type makes that
  checkable rather than leaving it to a reader's goodwill.

NO LOOKAHEAD, STRUCTURALLY. The prior is a function of the observed requests
only. Its signature takes the observed set and the instance geometry, and there
is no parameter through which the unobserved remainder could enter -- so a
planner using it at arrival k cannot smuggle in knowledge of arrival k+1. The
conformance suite pins the observable form of this: two instances that agree on
the observed prefix produce identical priors and identical capacity values
however different their futures are.

ACCESSIBILITY LABELS ARE ASSIGNED, NOT OBSERVED, on every instance this runs on
(ADR-0065; see `compatibility.ASSIGNED_ACCESSIBILITY_NOTE`). The accessible
foreclosure count is therefore a demonstration that the method discriminates
between cohorts, and is NOT evidence about the exposure any real fleet's
wheelchair users face.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from random import Random
from typing import Sequence

from metis.decide.compatibility import (
    AccessibilityProfile,
    CompatibilityEdge,
    CompatibilityGraph,
    admits_insertion,
    with_capacity_features,
)
from metis.decide.darp_ir import DarpInstance, DarpNode

CAPACITY_VALUE_VERSION = "0.5.0"

PRIOR_IS_AN_ASSUMPTION_NOTE = (
    "The scenario distribution is a PLACEHOLDER PRIOR built by resampling already-observed requests "
    "and displacing them in space and time. It is not a demand forecast and no forecasting model is "
    "wired into it. Absolute foreclosure counts inherit that assumption; what is comparable across "
    "placements is their ORDERING, because every placement is scored against the same draws."
)


# ==========================================================================
# Scenarios: hypothetical future requests.
# ==========================================================================

@dataclass(frozen=True)
class ScenarioRequest:
    """One hypothetical future trip. Deliberately the same shape as a real
    request's two nodes, so it can be spliced into a real instance and judged by
    the real checkers rather than by a simplified stand-in for them."""

    pickup_x: float
    pickup_y: float
    dropoff_x: float
    dropoff_y: float
    pickup_tw: tuple[float, float]
    dropoff_tw: tuple[float, float]
    service_duration: float
    load: int
    needs_wheelchair: bool
    template_request: int


@dataclass(frozen=True)
class DemandPrior:
    """What the scheduler believes about demand it has not seen yet.

    Built ONLY from observed requests -- there is no parameter through which the
    unobserved remainder can enter. `observed` is recorded so a report can state
    how much the prior was fitted on; a prior from two observations is a guess
    wearing a distribution's clothes and the count is the only warning available.
    """

    instance_name: str
    observed: tuple[int, ...]
    wheelchair_share: float
    jitter: float
    max_time_shift: float
    horizon: tuple[float, float]
    note: str = PRIOR_IS_AN_ASSUMPTION_NOTE


def prior_from_observed(
    instance: DarpInstance,
    profile: AccessibilityProfile,
    observed: Sequence[int],
    *,
    jitter_fraction: float = 0.15,
    max_time_shift: float = 120.0,
) -> DemandPrior:
    """Fit the placeholder prior to the requests the scheduler has already seen.

    NO LOOKAHEAD: `observed` is the only request information that enters, and the
    instance contributes geometry (the depot window) that a dispatcher knows on
    day one. Nothing about the unobserved remainder is reachable from here, which
    is what makes a planner built on this a genuinely online planner rather than
    an offline one wearing an online harness's name.

    `jitter_fraction` is expressed against the mean pickup-to-drop-off distance of
    the observed trips, so the spatial displacement scales with the service area
    rather than with an arbitrary absolute figure.
    """
    obs = tuple(sorted(int(r) for r in observed))
    if not obs:
        raise ValueError("a prior needs at least one observed request; there is nothing to resample")
    depot = instance.nodes[instance.depot_start]
    end_depot = instance.nodes[instance.depot_end]
    mean_trip = statistics.fmean(
        instance.dist(instance.pickup_index(r), instance.dropoff_index(r)) for r in obs
    )
    share = sum(1 for r in obs if profile.needs_wheelchair(r)) / len(obs)
    return DemandPrior(
        instance_name=instance.name,
        observed=obs,
        wheelchair_share=share,
        jitter=jitter_fraction * mean_trip,
        max_time_shift=max_time_shift,
        horizon=(depot.tw_start, end_depot.tw_end),
    )


def sample_scenarios(
    instance: DarpInstance, prior: DemandPrior, count: int, *, seed: int
) -> tuple[ScenarioRequest, ...]:
    """Draw `count` hypothetical future trips from the prior. Reproducible from
    (instance name, prior's observed set, seed) so a capacity value can be
    recomputed and audited."""
    rng = Random(f"scenario/{prior.instance_name}/{seed}/{prior.observed}")
    lo, hi = prior.horizon
    out: list[ScenarioRequest] = []
    for _ in range(count):
        template = rng.choice(prior.observed)
        p = instance.nodes[instance.pickup_index(template)]
        d = instance.nodes[instance.dropoff_index(template)]
        shift = rng.uniform(-prior.max_time_shift, prior.max_time_shift)

        def moved(tw: tuple[float, float]) -> tuple[float, float]:
            """Shift a window, but only if it is a TIGHT one. Cordeau type-a
            instances leave one end of each request effectively unconstrained
            ([0, 1440] against a 480-minute day); displacing that in time would
            change nothing except to make the instance look different."""
            a, b = tw
            if b - a >= (hi - lo):
                return tw
            width = b - a
            start = min(max(a + shift, lo), max(lo, hi - width))
            return (start, start + width)

        out.append(
            ScenarioRequest(
                pickup_x=p.x + rng.gauss(0.0, prior.jitter),
                pickup_y=p.y + rng.gauss(0.0, prior.jitter),
                dropoff_x=d.x + rng.gauss(0.0, prior.jitter),
                dropoff_y=d.y + rng.gauss(0.0, prior.jitter),
                pickup_tw=moved((p.tw_start, p.tw_end)),
                dropoff_tw=moved((d.tw_start, d.tw_end)),
                service_duration=p.service_duration,
                load=abs(p.load),
                needs_wheelchair=rng.random() < prior.wheelchair_share,
                template_request=template,
            )
        )
    return tuple(out)


# ==========================================================================
# The lens: one draw of scenarios, spliced into the real instance.
# ==========================================================================

def _extend(
    instance: DarpInstance, profile: AccessibilityProfile, scenarios: Sequence[ScenarioRequest]
) -> tuple[DarpInstance, AccessibilityProfile, dict[int, int]]:
    """Build an instance containing the real requests AND the scenario ones.

    Why splice rather than write a bespoke "could this hypothetical trip fit"
    routine: a bespoke routine would be a second, private copy of the constraint
    system, and a private copy is exactly how a generator and a checker drift into
    agreeing with each other and no one else. Splicing means the scenario trips
    are judged by `feasibility.check_darp_feasibility` and the equipment checker,
    unmodified, on identical terms to real ones.

    Returns the extended instance, the extended profile, and the map from base
    node indices to extended ones (drop-off indices shift, because there are more
    requests between the pickups and the drop-offs).
    """
    n = instance.num_requests
    m = len(scenarios)
    N = n + m
    nodes: list[DarpNode] = []
    depot = instance.nodes[instance.depot_start]
    end_depot = instance.nodes[instance.depot_end]

    nodes.append(DarpNode(0, depot.x, depot.y, depot.service_duration, 0, depot.tw_start, depot.tw_end))
    for r in range(1, n + 1):
        p = instance.nodes[instance.pickup_index(r)]
        nodes.append(DarpNode(r, p.x, p.y, p.service_duration, p.load, p.tw_start, p.tw_end))
    for j, s in enumerate(scenarios, start=1):
        nodes.append(
            DarpNode(n + j, s.pickup_x, s.pickup_y, s.service_duration, s.load, s.pickup_tw[0], s.pickup_tw[1])
        )
    for r in range(1, n + 1):
        d = instance.nodes[instance.dropoff_index(r)]
        nodes.append(DarpNode(N + r, d.x, d.y, d.service_duration, d.load, d.tw_start, d.tw_end))
    for j, s in enumerate(scenarios, start=1):
        nodes.append(
            DarpNode(
                N + n + j, s.dropoff_x, s.dropoff_y, s.service_duration, -s.load,
                s.dropoff_tw[0], s.dropoff_tw[1],
            )
        )
    nodes.append(
        DarpNode(2 * N + 1, end_depot.x, end_depot.y, end_depot.service_duration, 0,
                 end_depot.tw_start, end_depot.tw_end)
    )

    extended = DarpInstance.build(
        name=f"{instance.name}+{m}scen",
        num_vehicles=instance.num_vehicles,
        num_requests=N,
        max_route_duration=instance.max_route_duration,
        vehicle_capacity=instance.vehicle_capacity,
        max_ride_time=instance.max_ride_time,
        nodes=nodes,
    )
    remap = {instance.depot_start: 0, instance.depot_end: 2 * N + 1}
    for r in range(1, n + 1):
        remap[instance.pickup_index(r)] = r
        remap[instance.dropoff_index(r)] = N + r

    ext_profile = AccessibilityProfile(
        instance_name=extended.name,
        num_requests=N,
        num_vehicles=profile.num_vehicles,
        wheelchair_requests=frozenset(profile.wheelchair_requests)
        | frozenset(n + j for j, s in enumerate(scenarios, start=1) if s.needs_wheelchair),
        accessible_vehicles=profile.accessible_vehicles,
        wheelchair_positions=profile.wheelchair_positions,
        wheelchair_footprint=profile.wheelchair_footprint,
        seed=profile.seed,
        wheelchair_share=profile.wheelchair_share,
        provenance=profile.provenance,
    )
    return extended, ext_profile, remap


@dataclass(frozen=True)
class CapacityLens:
    """One draw of scenario demand, spliced into the instance, ready to be asked
    what a fleet state still has room for.

    Built once and reused across every question a planner asks at one decision
    point: the extended distance matrix and the scenario set are fixed, so the
    only thing that varies between calls is the fleet state, which is exactly the
    variable under study.
    """

    base: DarpInstance
    profile: AccessibilityProfile
    scenarios: tuple[ScenarioRequest, ...]
    extended: DarpInstance
    extended_profile: AccessibilityProfile
    remap: dict[int, int]
    draw_seed: int

    @property
    def scenario_ids(self) -> tuple[int, ...]:
        n = self.base.num_requests
        return tuple(range(n + 1, n + 1 + len(self.scenarios)))

    def accessible_scenario_ids(self) -> tuple[int, ...]:
        return tuple(r for r in self.scenario_ids if self.extended_profile.needs_wheelchair(r))

    def project(self, routes: Sequence[Sequence[int]]) -> list[list[int]]:
        """Rewrite base-indexed routes into the extended indexing."""
        return [[self.remap[node] for node in seq] for seq in routes]

    def reach(self, routes: Sequence[Sequence[int]]) -> tuple[int, int]:
        """(scenario trips still servable, of which accessible) given this fleet.

        A scenario trip counts only if some vehicle admits a CERTIFIED insertion
        of it -- an exact schedule that both independent checkers accept. This is
        the one place the estimate touches feasibility, and it does not
        approximate it.

        MARGINAL, not simultaneous: each scenario trip is asked about on its own,
        against the fleet as it stands. Two trips can each be reachable without
        both being servable together, so this is an upper bound on how many of a
        draw could actually be carried. That is the right quantity for the
        question being asked -- "which likely future requests does this commitment
        make infeasible" is a per-request question -- but it is not a forecast of
        how many trips the day will fit, and must not be read as one.
        """
        projected = self.project(routes)
        served = 0
        accessible = 0
        for s in self.scenario_ids:
            ok = any(
                admits_insertion(self.extended, self.extended_profile, v, seq, s)
                for v, seq in enumerate(projected)
            )
            if ok:
                served += 1
                if self.extended_profile.needs_wheelchair(s):
                    accessible += 1
        return served, accessible

    def reach_matrix(self, routes: Sequence[Sequence[int]]) -> tuple[frozenset[int], ...]:
        """Per scenario, the SET of vehicles that admit it -- not merely whether
        one does.

        Costs K times a plain `reach` and buys back far more inside a planning
        loop: a planner evaluating placements at one arrival changes exactly one
        vehicle's route, so every scenario still reachable through an untouched
        vehicle needs no re-evaluation at all. Without this the capacity term is
        the dominant cost of planning and the whole idea stops being usable at
        decision time, which is the one thing it exists to be.
        """
        projected = self.project(routes)
        return tuple(
            frozenset(
                v
                for v, seq in enumerate(projected)
                if admits_insertion(self.extended, self.extended_profile, v, seq, s)
            )
            for s in self.scenario_ids
        )

    def reach_from(self, matrix: Sequence[frozenset[int]]) -> tuple[int, int]:
        return (
            sum(1 for m in matrix if m),
            sum(
                1
                for s, m in zip(self.scenario_ids, matrix)
                if m and self.extended_profile.needs_wheelchair(s)
            ),
        )

    def reach_with_replacement(
        self, matrix: Sequence[frozenset[int]], vehicle: int, new_sequence: Sequence[int]
    ) -> tuple[int, int]:
        """Reach after ONE vehicle's route is replaced, reusing `matrix` for the
        rest. Exactly equal to `reach` on the resulting fleet -- the other
        vehicles' routes are unchanged, so their entries in the matrix are still
        correct by construction, and the conformance suite pins that equality
        rather than trusting the argument."""
        seq = [self.remap[node] for node in new_sequence]
        served = 0
        accessible = 0
        for s, m in zip(self.scenario_ids, matrix):
            ok = bool(m - {vehicle}) or admits_insertion(
                self.extended, self.extended_profile, vehicle, seq, s
            )
            if ok:
                served += 1
                if self.extended_profile.needs_wheelchair(s):
                    accessible += 1
        return served, accessible


def build_lens(
    instance: DarpInstance,
    profile: AccessibilityProfile,
    prior: DemandPrior,
    *,
    scenarios: int = 10,
    seed: int = 0,
) -> CapacityLens:
    drawn = sample_scenarios(instance, prior, scenarios, seed=seed)
    extended, ext_profile, remap = _extend(instance, profile, drawn)
    return CapacityLens(
        base=instance,
        profile=profile,
        scenarios=drawn,
        extended=extended,
        extended_profile=ext_profile,
        remap=remap,
        draw_seed=seed,
    )


# ==========================================================================
# The estimate.
# ==========================================================================

@dataclass(frozen=True)
class CapacityValue:
    """The opportunity cost of a commitment, in future trips foreclosed.

    `trips_foreclosed` is the mean across independent scenario draws;
    `stderr` is the standard error of that mean. Read them together and only
    together -- a difference between two placements smaller than the standard
    error is sampling noise, and `distinguishable_from` says so rather than
    leaving the reader to eyeball it.

    `accessible_trips_foreclosed` is the same quantity restricted to scenario
    trips needing a wheelchair-accessible vehicle. It is the number the packet
    exists for: an aggregate that hides a disabled rider losing their trip is the
    failure mode, so the cohort figure travels with the total everywhere.
    """

    draws: int
    scenarios_per_draw: int
    accessible_scenarios_per_draw: float
    reach_before: float
    reach_after: float
    accessible_reach_before: float
    accessible_reach_after: float
    trips_foreclosed: float
    accessible_trips_foreclosed: float
    stderr: float
    accessible_stderr: float
    per_draw: tuple[tuple[int, int], ...]
    prior_note: str = PRIOR_IS_AN_ASSUMPTION_NOTE
    version: str = CAPACITY_VALUE_VERSION

    def distinguishable_from(self, other: "CapacityValue") -> bool:
        """Is the difference between two placements' foreclosure larger than the
        sampling noise in the estimate? A planner may prefer the lower one either
        way -- it has to choose something -- but a REPORT that quotes the
        difference as a finding must consult this first."""
        pooled = math.hypot(self.stderr, other.stderr)
        return abs(self.trips_foreclosed - other.trips_foreclosed) > pooled

    def to_record(self) -> dict:
        return {
            "draws": self.draws,
            "scenarios_per_draw": self.scenarios_per_draw,
            "accessible_scenarios_per_draw": round(self.accessible_scenarios_per_draw, 4),
            "reach_before": round(self.reach_before, 4),
            "reach_after": round(self.reach_after, 4),
            "accessible_reach_before": round(self.accessible_reach_before, 4),
            "accessible_reach_after": round(self.accessible_reach_after, 4),
            "trips_foreclosed": round(self.trips_foreclosed, 4),
            "accessible_trips_foreclosed": round(self.accessible_trips_foreclosed, 4),
            "stderr": round(self.stderr, 4),
            "accessible_stderr": round(self.accessible_stderr, 4),
            "prior_note": self.prior_note,
            "version": self.version,
        }


@dataclass(frozen=True)
class CapacitySnapshot:
    """The fleet's reach, computed once, before a planner evaluates placements.

    Exists so every candidate placement at one arrival is compared against the
    SAME baseline and the same draws. Recomputing the baseline per option would
    both waste the work and let scenario noise leak into the comparison between
    options, which is the one comparison that has to be clean.
    """

    routes: tuple[tuple[int, ...], ...]
    matrices: tuple[tuple[frozenset[int], ...], ...]
    reach_before: float
    accessible_reach_before: float
    per_lens_before: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class CapacityEnsemble:
    """Several independent scenario draws, so the estimate carries an error bar.

    One draw gives a number with no way to tell a real difference from a lucky
    sample. The ensemble is the cheapest thing that makes the estimate honest, and
    the draw count is the knob a caller trades against planning latency.
    """

    lenses: tuple[CapacityLens, ...]

    @property
    def draws(self) -> int:
        return len(self.lenses)

    def reach(self, routes: Sequence[Sequence[int]]) -> tuple[float, float]:
        pairs = [lens.reach(routes) for lens in self.lenses]
        return (
            statistics.fmean(p[0] for p in pairs),
            statistics.fmean(p[1] for p in pairs),
        )

    def value_of(
        self, before: Sequence[Sequence[int]], after: Sequence[Sequence[int]]
    ) -> CapacityValue:
        """How many likely future trips the move from `before` to `after` forecloses.

        Both states are evaluated against the SAME draws, so the difference is the
        commitment and not the sample. That pairing is what makes a small
        foreclosure count meaningful at all -- comparing two states against
        independent draws would bury the signal in scenario variance.
        """
        totals: list[tuple[int, int]] = []
        acc_deltas: list[int] = []
        deltas: list[int] = []
        rb = ra = arb = ara = 0.0
        for lens in self.lenses:
            b_all, b_acc = lens.reach(before)
            a_all, a_acc = lens.reach(after)
            deltas.append(b_all - a_all)
            acc_deltas.append(b_acc - a_acc)
            totals.append((b_all - a_all, b_acc - a_acc))
            rb += b_all
            ra += a_all
            arb += b_acc
            ara += a_acc
        k = len(self.lenses)
        acc_per_draw = statistics.fmean(len(l.accessible_scenario_ids()) for l in self.lenses)
        return CapacityValue(
            draws=k,
            scenarios_per_draw=len(self.lenses[0].scenarios),
            accessible_scenarios_per_draw=acc_per_draw,
            reach_before=rb / k,
            reach_after=ra / k,
            accessible_reach_before=arb / k,
            accessible_reach_after=ara / k,
            trips_foreclosed=statistics.fmean(deltas),
            accessible_trips_foreclosed=statistics.fmean(acc_deltas),
            stderr=(statistics.stdev(deltas) / math.sqrt(k)) if k > 1 else 0.0,
            accessible_stderr=(statistics.stdev(acc_deltas) / math.sqrt(k)) if k > 1 else 0.0,
            per_draw=tuple(totals),
        )

    def snapshot(self, routes: Sequence[Sequence[int]]) -> CapacitySnapshot:
        mats = tuple(lens.reach_matrix(routes) for lens in self.lenses)
        before = tuple(lens.reach_from(m) for lens, m in zip(self.lenses, mats))
        return CapacitySnapshot(
            routes=tuple(tuple(seq) for seq in routes),
            matrices=mats,
            reach_before=statistics.fmean(b[0] for b in before),
            accessible_reach_before=statistics.fmean(b[1] for b in before),
            per_lens_before=before,
        )

    def value_of_replacement(
        self, snapshot: CapacitySnapshot, vehicle: int, new_sequence: Sequence[int]
    ) -> CapacityValue:
        """Foreclosure caused by replacing ONE vehicle's route, against a snapshot.

        The planner's inner loop. Equal to `value_of(snapshot.routes, after)` by
        construction and pinned equal by the conformance suite -- an incremental
        shortcut that silently disagreed with the definition it shortcuts would be
        worse than no shortcut.
        """
        deltas: list[int] = []
        acc_deltas: list[int] = []
        ra = ara = 0.0
        for lens, mat, (b_all, b_acc) in zip(self.lenses, snapshot.matrices, snapshot.per_lens_before):
            a_all, a_acc = lens.reach_with_replacement(mat, vehicle, new_sequence)
            deltas.append(b_all - a_all)
            acc_deltas.append(b_acc - a_acc)
            ra += a_all
            ara += a_acc
        k = len(self.lenses)
        return CapacityValue(
            draws=k,
            scenarios_per_draw=len(self.lenses[0].scenarios),
            accessible_scenarios_per_draw=statistics.fmean(
                len(l.accessible_scenario_ids()) for l in self.lenses
            ),
            reach_before=snapshot.reach_before,
            reach_after=ra / k,
            accessible_reach_before=snapshot.accessible_reach_before,
            accessible_reach_after=ara / k,
            trips_foreclosed=statistics.fmean(deltas),
            accessible_trips_foreclosed=statistics.fmean(acc_deltas),
            stderr=(statistics.stdev(deltas) / math.sqrt(k)) if k > 1 else 0.0,
            accessible_stderr=(statistics.stdev(acc_deltas) / math.sqrt(k)) if k > 1 else 0.0,
            per_draw=tuple(zip(deltas, acc_deltas)),
        )

    def residual(self, routes: Sequence[Sequence[int]]) -> tuple[float, float]:
        """ACCESSIBLE CAPACITY PRESERVED, and total capacity preserved, for a
        finished plan: the mean number of scenario trips the plan can still
        absorb, and how many of those need a wheelchair-accessible vehicle.

        This is the headline distributional metric of the packet. It is a forward
        statement about the fleet a plan leaves behind -- not a count of who was
        served, which a plan can always inflate by pooling ambulatory riders while
        quietly consuming every wheelchair position on the road.
        """
        return self.reach(routes)


def build_ensemble(
    instance: DarpInstance,
    profile: AccessibilityProfile,
    prior: DemandPrior,
    *,
    draws: int = 4,
    scenarios: int = 10,
    seed: int = 0,
) -> CapacityEnsemble:
    if draws < 1:
        raise ValueError("an ensemble needs at least one draw")
    return CapacityEnsemble(
        lenses=tuple(
            build_lens(instance, profile, prior, scenarios=scenarios, seed=seed * 1_000 + d)
            for d in range(draws)
        )
    )


def empty_routes(instance: DarpInstance) -> list[list[int]]:
    return [[instance.depot_start, instance.depot_end] for _ in range(instance.num_vehicles)]


def attach_capacity_features(
    graph: CompatibilityGraph, ensemble: CapacityEnsemble
) -> CompatibilityGraph:
    """Fill in each edge's 'effect on future capacity' feature.

    Measured as the foreclosure caused by running that share as the only route on
    its vehicle, against an otherwise empty fleet. That isolates the share's own
    demand on capacity from whatever else a plan happens to contain, which is what
    makes the feature comparable between edges.

    Separated from `build_compatibility_graph` on purpose: it is the only feature
    that is an ESTIMATE rather than a measurement, and it costs orders of
    magnitude more. A caller who does not want to pay for it gets None in the two
    fields and can never mistake an unfilled estimate for a computed zero.
    """
    base = empty_routes(ensemble.lenses[0].base)

    def enriched(edge: CompatibilityEdge) -> CompatibilityEdge:
        after = [list(seq) for seq in base]
        after[edge.vehicle] = list(edge.certificate.sequence)
        value = ensemble.value_of(base, after)
        return with_capacity_features(
            edge,
            cost=value.trips_foreclosed,
            accessible_cost=value.accessible_trips_foreclosed,
        )

    return CompatibilityGraph(
        instance_name=graph.instance_name,
        profile=graph.profile,
        nodes=graph.nodes,
        edges=tuple(enriched(e) for e in graph.edges),
        hyperedges=tuple(enriched(e) for e in graph.hyperedges),
        max_group_size=graph.max_group_size,
        proposals_scored=graph.proposals_scored,
        proposals_certified=graph.proposals_certified,
        rejections_by_checker=graph.rejections_by_checker,
        scorer_name=graph.scorer_name,
        truncated=graph.truncated,
        equipment_layer_can_bind=graph.equipment_layer_can_bind,
    )
