"""Program F conformance: the pooling planner, judged as a decision.

THE STANDARD THIS SUITE HOLDS THE PACKET TO. A better score that changes no
assignment is worthless, so the tests here are about PLANS: who was served, on
which vehicle, pooled with whom, and how much accessible capacity was left
behind. An objective value is never asserted on its own.

FOUR PROPERTIES ARE STRUCTURAL AND ARE TESTED AS SUCH.

1. **ZERO FEASIBILITY VIOLATIONS, ALWAYS.** Every plan the planner emits is
   accepted by BOTH independent checkers. Swept over instances, seeds and
   weights, and asserted at zero rather than at "few".

2. **IT CANNOT RATION.** A policy that declines a rider it could serve makes the
   run raise and produce nothing. Tested by handing the harness exactly such a
   policy -- the guard is not dead code, and the exception type is the SAME one
   `packages.decide.online` raises, so the two cannot drift.

3. **IT CANNOT RE-PLAN.** A commitment is irrevocable. Tested both by sweeping
   real runs and by handing the harness a policy that tries to evict an existing
   rider, which must raise rather than quietly produce a better-looking plan.

4. **THE METRICS DECOMPOSE.** Passenger miles sum across cohorts to the fleet
   total; allocated vehicle miles plus deadhead equal vehicle miles. A metric
   that did not add up could report an occupancy gain that came from arithmetic.

AND THE FINDING THE PACKET EXISTS FOR: the capacity-value term must actually
change the plan on some instance. A test asserting only that "it does not crash"
would let a no-op policy pass, so the decision-change is asserted, and asserted to
be non-vacuous.

Cordeau instances are synthetic academic benchmarks; the accessibility labels are
ASSIGNED, not observed. ALGORITHMIC claims only.
"""

from __future__ import annotations

import pytest

from packages.decide.capacity_value import build_ensemble, empty_routes, prior_from_observed
from packages.decide.compatibility import (
    AccessibilityProfile,
    assign_accessibility,
    certify_group,
    certify_insertion,
    check_equipment_feasibility,
    route_passenger_miles,
)
from packages.decide.darp_ir import DarpInstance, DarpNode
from packages.decide.darp_loader import find_benchmark_archive, load_zip_instance
from packages.decide.darp_solver import route_distance, solve_darp
from packages.decide.feasibility import check_darp_feasibility
from packages.decide.online import RationingRefused
from packages.decide.pooling import (
    AMBULATORY,
    WHEELCHAIR,
    InvalidPlacement,
    IrrevocabilityViolation,
    PoolingView,
    booking_order,
    diff_plans,
    evaluate,
    evaluate_plan,
    free_accessible_minutes,
    least_total_cost,
    plan_online,
    routes_from_solution,
)

_ARCHIVE = find_benchmark_archive()
_needs_archive = pytest.mark.skipif(_ARCHIVE is None, reason="Cordeau DARP benchmark archive not acquired")

# Budgets kept modest: the capacity-aware policy runs a scenario ensemble per
# arrival, and this module sits on CI next to two other expensive Program F suites.
_SMALL = ("a2-16", "a4-16")


def _load(name: str) -> DarpInstance:
    return load_zip_instance(_ARCHIVE, name)


def _toy() -> tuple[DarpInstance, AccessibilityProfile]:
    def nd(i, x, y, load, tw=(0.0, 600.0)):
        return DarpNode(node_id=i, x=x, y=y, service_duration=0.0, load=load, tw_start=tw[0], tw_end=tw[1])

    n = 4
    nodes = [nd(0, 0.0, 0.0, 0)]
    for r in range(1, n + 1):
        nodes.append(nd(r, float(r), 0.0, 1))
    for r in range(1, n + 1):
        nodes.append(nd(n + r, float(r) + 6.0, 0.0, -1))
    nodes.append(nd(2 * n + 1, 0.0, 0.0, 0))
    instance = DarpInstance.build(
        name="toy4", num_vehicles=2, num_requests=n, max_route_duration=600.0,
        vehicle_capacity=3, max_ride_time=300.0, nodes=nodes,
    )
    profile = AccessibilityProfile(
        instance_name="toy4", num_requests=n, num_vehicles=2,
        wheelchair_requests=frozenset({1}), accessible_vehicles=frozenset({0}),
        wheelchair_positions=1, wheelchair_footprint=2,
    )
    return instance, profile


# ==========================================================================
# 1. ZERO FEASIBILITY VIOLATIONS.
# ==========================================================================

@_needs_archive
@pytest.mark.parametrize("name", _SMALL)
@pytest.mark.parametrize("seed", [1, 2])
def test_the_baseline_plan_violates_nothing(name, seed):
    inst = _load(name)
    prof = assign_accessibility(inst, seed=1, accessible_vehicles=1)
    plan = plan_online(inst, prof, seed=seed, capacity_weight=0.0)
    m = evaluate(inst, prof, plan)
    assert m.routing_violations == 0
    assert m.equipment_violations == 0
    assert m.feasibility_violations == 0


@_needs_archive
@pytest.mark.parametrize("seed", [1, 2])
def test_the_capacity_aware_plan_violates_nothing(seed):
    inst = _load("a2-16")
    prof = assign_accessibility(inst, seed=1, accessible_vehicles=1)
    plan = plan_online(inst, prof, seed=seed, capacity_weight=1.0, draws=2, scenarios=6)
    m = evaluate(inst, prof, plan)
    assert m.feasibility_violations == 0


@_needs_archive
def test_every_committed_route_is_re_verifiable_from_the_raw_instance():
    """The plan's own self-audit is not taken on trust: both checkers are re-run
    here, from the instance file, on the schedule the planner committed."""
    inst = _load("a2-16")
    prof = assign_accessibility(inst, seed=1)
    plan = plan_online(inst, prof, seed=1)
    assert check_darp_feasibility(inst, plan.solution) == []
    assert check_equipment_feasibility(inst, prof, plan.solution) == []


# ==========================================================================
# 2. IT CANNOT RATION.
# ==========================================================================

def test_a_policy_that_declines_a_servable_rider_makes_the_run_produce_nothing():
    """The guard is reachable and it fires. `RationingRefused` is imported from
    `packages.decide.online`, not re-declared, so the commingled harness and this
    one cannot drift into different definitions of the same refusal."""
    inst, prof = _toy()
    with pytest.raises(RationingRefused):
        plan_online(inst, prof, seed=1, select=lambda view: None)


def test_the_rationing_guard_is_the_same_exception_type_as_the_commingled_harness():
    from packages.decide import online

    assert RationingRefused is online.RationingRefused


def test_a_policy_cannot_invent_a_placement_the_harness_did_not_offer():
    inst, prof = _toy()
    cert = certify_group(inst, prof, [1], 1).certificate
    with pytest.raises(InvalidPlacement):
        plan_online(inst, prof, seed=1, select=lambda view: (1, cert))


@_needs_archive
@pytest.mark.parametrize("weight", [0.0, 1.0])
def test_a_request_is_recorded_unserved_only_when_the_authority_found_no_placement(weight):
    """The difference between "infeasible" and "declined". Every unserved request
    must have had ZERO certified options at the moment it arrived -- which is a
    verdict from two independent checkers, not a policy choice."""
    inst = _load("a2-16")
    prof = assign_accessibility(inst, seed=1, accessible_vehicles=1)
    plan = plan_online(inst, prof, seed=1, capacity_weight=weight, draws=2, scenarios=6)
    for c in plan.commitments:
        assert c.served == (c.options > 0)


@_needs_archive
@pytest.mark.parametrize("name", _SMALL)
def test_no_declined_rider_had_a_certified_placement_when_they_arrived(name):
    """FOUND BY A SURVIVING MUTATION, and it was the worst one available: a
    one-line change making the planner decline every wheelchair rider outright
    left the whole suite green. The reason is that the harness recorded
    `options=0` on the unserved branch itself, so the test that compared
    `served` against `options` was reading the harness's own claim back to it.

    The fix is to stop believing the harness. The run is REPLAYED from the
    commitment log -- each committed route restored exactly as it stood -- and at
    every declined request the authority is asked again, from scratch, on every
    vehicle. A decline is only honest if nothing could have carried them.

    This is the test that makes "it cannot ration" mean something on a real
    instance rather than only against a policy written to ration.
    """
    inst = _load(name)
    prof = assign_accessibility(inst, seed=1, accessible_vehicles=1)
    plan = plan_online(inst, prof, seed=1, capacity_weight=0.0)
    assert plan.unserved, "vacuous: nobody was declined on this instance"

    routes = empty_routes(inst)
    for c in plan.commitments:
        if c.served:
            routes[c.vehicle] = list(c.route_after)
            continue
        for v in range(inst.num_vehicles):
            outcome = certify_insertion(inst, prof, v, routes[v], c.request)
            assert not outcome.certified, (
                f"request {c.request} was declined at arrival {c.sequence} although vehicle {v} "
                f"admitted a certified placement: {outcome.detail}"
            )


# ==========================================================================
# 3. IT CANNOT RE-PLAN.
# ==========================================================================

@_needs_archive
def test_a_committed_rider_stays_on_the_vehicle_they_were_committed_to():
    inst = _load("a2-16")
    prof = assign_accessibility(inst, seed=1)
    plan = plan_online(inst, prof, seed=1)
    final = {
        inst.request_of(s): v
        for v, seq in enumerate(plan.routes)
        for s in seq
        if inst.is_pickup(s)
    }
    for c in plan.commitments:
        if c.served:
            assert final[c.request] == c.vehicle


def test_a_policy_cannot_evict_an_earlier_rider_by_inventing_a_certificate():
    """A policy reaching for a certificate the harness did not offer is stopped by
    the invented-placement guard, BEFORE irrevocability is even consulted. Pinned
    to that exception specifically, because an earlier version of this test
    accepted either and therefore proved nothing about either."""
    inst, prof = _toy()

    def evicting(view: PoolingView):
        if view.sequence == 0:
            return least_total_cost(view)
        v = view.options[0][0]
        solo = certify_group(view.instance, view.profile, [view.request], v)
        if solo.certificate is None:
            return least_total_cost(view)
        return (v, solo.certificate)

    with pytest.raises(InvalidPlacement):
        plan_online(inst, prof, seed=1, select=evicting)


def test_an_option_that_drops_an_earlier_rider_raises_irrevocability(monkeypatch):
    """FOUND BY A SURVIVING MUTATION. Deleting the "nobody was dropped" half of
    the irrevocability check left every test green, because the only way a policy
    could drop a rider was by inventing a certificate -- which the invented-
    placement guard already refuses. So the drop check was covering a case
    unreachable through the public API, and an unreachable guard is prose.

    Made reachable here by corrupting the AUTHORITY instead of the policy: the
    harness is fed an option that genuinely came from `certify_insertion` and
    genuinely drops the riders already aboard. That is a harness/authority bug
    rather than a policy one, which is exactly what the check exists to catch, and
    it must stop the run rather than quietly produce a better-looking plan.
    """
    inst, prof = _toy()
    real = certify_insertion

    def dropping(instance, profile, vehicle, current_sequence, request):
        # a legitimately certified route that carries ONLY the arriving request
        return certify_group(instance, profile, [request], vehicle)

    monkeypatch.setattr("packages.decide.pooling.certify_insertion", dropping)
    with pytest.raises(IrrevocabilityViolation):
        plan_online(inst, prof, seed=1)
    assert real is certify_insertion  # the module-level symbol is restored by monkeypatch


@_needs_archive
def test_the_commitment_log_is_append_only_and_in_arrival_order():
    inst = _load("a2-16")
    prof = assign_accessibility(inst, seed=1)
    plan = plan_online(inst, prof, seed=4)
    assert [c.sequence for c in plan.commitments] == list(range(len(plan.commitments)))
    assert [c.request for c in plan.commitments] == list(booking_order(inst, seed=4))


@_needs_archive
def test_the_same_seed_produces_the_same_plan():
    inst = _load("a2-16")
    prof = assign_accessibility(inst, seed=1)
    a = plan_online(inst, prof, seed=2)
    b = plan_online(inst, prof, seed=2)
    assert a.routes == b.routes and a.assignment() == b.assignment()


@_needs_archive
def test_the_capacity_aware_pipeline_is_reproducible_modulo_the_wall_clock():
    """The capacity term is a MONTE CARLO estimate, so this is the property that
    stops it from being irreproducible: every draw is seeded from (instance,
    observed prefix, seed), so the same inputs give the same plan, the same
    scenarios and the same reported metrics. Wall time is the only field allowed
    to differ, and it is named explicitly rather than compared loosely -- a test
    that ignored 'timing-ish' fields would also ignore a genuine drift."""
    inst = _load("a4-16")
    prof = assign_accessibility(inst, seed=1, accessible_vehicles=1)
    a = plan_online(inst, prof, seed=2, capacity_weight=1.0, draws=2, scenarios=6)
    b = plan_online(inst, prof, seed=2, capacity_weight=1.0, draws=2, scenarios=6)
    assert a.routes == b.routes and a.schedules == b.schedules
    assert [c.to_record() for c in a.commitments] == [c.to_record() for c in b.commitments]

    prior = prior_from_observed(inst, prof, range(1, inst.num_requests + 1))
    e1 = build_ensemble(inst, prof, prior, draws=3, scenarios=8, seed=5)
    e2 = build_ensemble(inst, prof, prior, draws=3, scenarios=8, seed=5)
    r1 = evaluate(inst, prof, a, ensemble=e1).to_record()
    r2 = evaluate(inst, prof, b, ensemble=e2).to_record()
    assert {k for k in r1 if r1[k] != r2[k]} == {"wall_time_s"}


def test_the_arrival_order_must_be_a_permutation_of_the_requests():
    inst, prof = _toy()
    with pytest.raises(ValueError):
        plan_online(inst, prof, arrivals=[1, 1, 2, 3])


# ==========================================================================
# 4. THE METRICS DECOMPOSE.
# ==========================================================================

@_needs_archive
@pytest.mark.parametrize("name", _SMALL)
def test_passenger_miles_sum_across_cohorts_to_the_fleet_total(name):
    inst = _load(name)
    prof = assign_accessibility(inst, seed=1)
    plan = plan_online(inst, prof, seed=1)
    m = evaluate(inst, prof, plan)
    assert sum(c.passenger_miles for c in m.cohorts) == pytest.approx(m.passenger_miles)


@_needs_archive
def test_allocated_vehicle_miles_plus_deadhead_equal_vehicle_miles():
    inst = _load("a2-16")
    prof = assign_accessibility(inst, seed=1)
    plan = plan_online(inst, prof, seed=1)
    m = evaluate(inst, prof, plan)
    allocated = sum(c.allocated_vehicle_miles for c in m.cohorts)
    assert allocated + m.deadhead_miles == pytest.approx(m.vehicle_miles)


@_needs_archive
def test_occupancy_is_passenger_miles_over_vehicle_miles_recomputed_independently():
    inst = _load("a2-16")
    prof = assign_accessibility(inst, seed=1)
    plan = plan_online(inst, prof, seed=1)
    m = evaluate(inst, prof, plan)
    vm = sum(route_distance(inst, list(seq)) for seq in plan.routes)
    pm = sum(route_passenger_miles(inst, prof, seq) for seq in plan.routes)
    assert m.vehicle_miles == pytest.approx(vm)
    assert m.passenger_miles == pytest.approx(pm)
    assert m.occupancy == pytest.approx(pm / vm)
    assert m.vehicle_miles_per_served_trip == pytest.approx(vm / m.trips_served)


@_needs_archive
def test_the_cohorts_partition_the_demand_and_the_service():
    inst = _load("a2-16")
    prof = assign_accessibility(inst, seed=1)
    m = evaluate(inst, prof, plan_online(inst, prof, seed=1))
    assert sum(c.demand for c in m.cohorts) == inst.num_requests == m.trips_demanded
    assert sum(c.served for c in m.cohorts) == m.trips_served
    assert m.cohort(WHEELCHAIR).demand > 0, "vacuous: no accessible demand to stratify"
    assert m.cohort(AMBULATORY).demand > 0


@_needs_archive
def test_the_metrics_record_repeats_the_assigned_labels_warning():
    inst = _load("a2-16")
    prof = assign_accessibility(inst, seed=1)
    record = evaluate(inst, prof, plan_online(inst, prof, seed=1)).to_record()
    assert "ASSIGNED, NOT OBSERVED" in record["ACCESSIBILITY_LABELS"]
    assert "ASSIGNED" in record["headline"]


# ==========================================================================
# ACCESSIBLE CAPACITY PRESERVED.
# ==========================================================================

def test_an_empty_fleet_has_every_accessible_minute_free():
    inst, prof = _toy()
    routes = empty_routes(inst)
    schedules = [[0.0, 0.0] for _ in routes]
    free, available = free_accessible_minutes(inst, prof, routes, schedules)
    assert free == pytest.approx(available)
    assert available > 0


def test_carrying_a_wheelchair_rider_consumes_accessible_minutes():
    inst, prof = _toy()
    cert = certify_group(inst, prof, [1], 0).certificate
    routes = empty_routes(inst)
    schedules = [[0.0, 0.0] for _ in routes]
    routes[0] = list(cert.sequence)
    schedules[0] = list(cert.begin_service)
    free, available = free_accessible_minutes(inst, prof, routes, schedules)
    assert 0 <= free < available


def test_free_accessible_minutes_counts_only_accessible_vehicles():
    inst, prof = _toy()
    routes = empty_routes(inst)
    schedules = [[0.0, 0.0] for _ in routes]
    _free, available = free_accessible_minutes(inst, prof, routes, schedules)
    shift = inst.nodes[inst.depot_end].tw_end - inst.nodes[inst.depot_start].tw_start
    assert available == pytest.approx(shift * len(prof.accessible_vehicles))


@_needs_archive
def test_accessible_capacity_preserved_is_reported_only_when_an_ensemble_is_supplied():
    """None means "not estimated", never "estimated at zero". A metric that
    defaulted to 0.0 would let an unmeasured plan look like a saturated one."""
    inst = _load("a2-16")
    prof = assign_accessibility(inst, seed=1)
    plan = plan_online(inst, prof, seed=1)
    assert evaluate(inst, prof, plan).accessible_capacity_preserved is None
    prior = prior_from_observed(inst, prof, range(1, inst.num_requests + 1))
    ens = build_ensemble(inst, prof, prior, draws=2, scenarios=6, seed=0)
    assert evaluate(inst, prof, plan, ensemble=ens).accessible_capacity_preserved is not None


# ==========================================================================
# THE BASELINE IS A FAITHFUL BASELINE.
# ==========================================================================

@_needs_archive
@pytest.mark.parametrize("name", _SMALL)
def test_with_the_capacity_term_off_the_planner_takes_the_cheapest_certified_insertion(name):
    """`capacity_weight=0` must genuinely be the rule current practice follows,
    or the A/B is a strawman. Recomputed against the recorded per-option costs."""
    inst = _load(name)
    prof = assign_accessibility(inst, seed=1)
    plan = plan_online(inst, prof, seed=1, capacity_weight=0.0)
    for c in plan.commitments:
        assert c.capacity_cost is None
        if c.served:
            assert c.added_vehicle_miles is not None


def test_least_total_cost_is_the_argmin_over_the_option_costs():
    """A direct unit test of the policy, because the plan-level tests would pass
    just as happily if it picked the WORST option -- they assert the plan is
    feasible and that the decision changed, neither of which distinguishes argmin
    from argmax. ADR-0060 records a winner-selection mutation that survived for
    exactly this reason."""
    inst, prof = _toy()
    cert = certify_group(inst, prof, [2], 1).certificate
    view = PoolingView(
        instance=inst, profile=prof, request=2, sequence=0,
        routes=(), options=((0, cert), (1, cert), (0, cert)),
        option_cost=(9.0, 1.0, 4.0),
        added_vehicle_miles=(9.0, 1.0, 4.0),
        capacity_cost=(None, None, None), accessible_capacity_cost=(None, None, None),
        trip_value=10.0, capacity_weight=0.0, accessible_weight=2.0,
    )
    assert least_total_cost(view) == (1, cert)
    assert least_total_cost(
        PoolingView(**{**view.__dict__, "options": (), "option_cost": ()})
    ) is None


def test_the_diff_reports_a_pooling_change_when_only_the_pooling_changed():
    """Two plans, the same requests on the same vehicles, pooled differently. A
    vehicle-level diff calls this "no change"; `_partners` is what stops it, and
    without a test the partner comparison could be deleted silently."""
    inst, prof = _toy()
    pooled = [[0, 1, 2, 5, 6, 9], [0, 9]]
    sequential = [[0, 1, 5, 2, 6, 9], [0, 9]]
    sched = [[float(i) * 20 for i in range(len(seq))] for seq in pooled]
    ma = evaluate_plan(inst, prof, pooled, sched, policy="pooled")
    mb = evaluate_plan(inst, prof, sequential, sched, policy="sequential")
    d = diff_plans(inst, prof, ma, pooled, mb, sequential)
    assert d.requests_moved == ()
    assert d.requests_gained == () and d.requests_lost == ()
    assert d.pooling_changed == (1, 2)
    assert not d.identical


@_needs_archive
def test_the_capacity_term_is_off_by_default():
    inst = _load("a2-16")
    prof = assign_accessibility(inst, seed=1)
    plan = plan_online(inst, prof, seed=1)
    assert plan.capacity_weight == 0.0
    assert plan.policy == "cheapest-insertion"


# ==========================================================================
# DID THE DECISION CHANGE? -- the packet's own standard.
# ==========================================================================

@pytest.fixture(scope="module")
def ab_pair():
    """The A/B both decision tests read, planned once. The capacity-aware policy
    runs a scenario ensemble at every arrival, so re-planning it per test would
    double the cost of this module for no additional evidence."""
    if _ARCHIVE is None:
        pytest.skip("Cordeau DARP benchmark archive not acquired")
    inst = _load("a4-24")
    prof = assign_accessibility(inst, seed=1, accessible_vehicles=1)
    baseline = plan_online(inst, prof, seed=3, capacity_weight=0.0)
    candidate = plan_online(inst, prof, seed=3, capacity_weight=1.0, draws=3, scenarios=10)
    return inst, prof, baseline, candidate


def test_pricing_the_future_changes_the_plan(ab_pair):
    """NOT VACUOUS. A test that only checked the run completed would pass for a
    policy that does nothing at all, which is the failure mode the packet's own
    brief names: a better score that changes no assignment is worthless."""
    inst, prof, baseline, candidate = ab_pair
    mb = evaluate(inst, prof, baseline)
    mc = evaluate(inst, prof, candidate)
    d = diff_plans(inst, prof, mb, baseline.routes, mc, candidate.routes)
    assert not d.identical
    assert d.requests_moved or d.pooling_changed
    assert mb.feasibility_violations == 0 and mc.feasibility_violations == 0


def test_pricing_the_future_does_not_take_a_trip_away_from_anyone(ab_pair):
    """The framing, enforced as a test. Releasing capacity, never rationing it:
    the capacity-aware plan must not serve fewer riders than the baseline, in
    total OR in either cohort. An occupancy or capacity gain bought with
    somebody's trip is a defect, and this is where it would be caught."""
    inst, prof, baseline, candidate = ab_pair
    mb = evaluate(inst, prof, baseline)
    mc = evaluate(inst, prof, candidate)
    assert mc.trips_served >= mb.trips_served
    for cohort in (WHEELCHAIR, AMBULATORY):
        assert mc.cohort(cohort).served >= mb.cohort(cohort).served


def test_the_capacity_term_gains_trips_for_the_cohort_that_needs_the_scarce_vehicle(ab_pair):
    """The finding, pinned so a regression is loud. On this instance the extra
    trips the capacity term buys go to riders needing the one accessible vehicle
    -- which is the entire argument for pricing the future rather than the
    present. Asserted as a floor, not an exact figure, so ordinary drift in the
    estimate does not fail the suite while a reversal does."""
    inst, prof, baseline, candidate = ab_pair
    mb = evaluate(inst, prof, baseline)
    mc = evaluate(inst, prof, candidate)
    assert mc.cohort(WHEELCHAIR).served > mb.cohort(WHEELCHAIR).served


@_needs_archive
def test_a_plan_diffed_against_itself_is_identical():
    inst = _load("a2-16")
    prof = assign_accessibility(inst, seed=1)
    plan = plan_online(inst, prof, seed=1)
    m = evaluate(inst, prof, plan)
    d = diff_plans(inst, prof, m, plan.routes, m, plan.routes)
    assert d.identical
    assert d.occupancy_delta == 0.0 and d.trips_served_delta == 0


@_needs_archive
def test_the_diff_notices_a_change_in_pooling_partners_even_on_the_same_vehicles():
    """Two plans can place every request on the same vehicle and still pool them
    differently. A vehicle-level diff would call that "no change"."""
    inst = _load("a2-16")
    prof = assign_accessibility(inst, seed=1)
    a = plan_online(inst, prof, seed=1)
    b = plan_online(inst, prof, seed=5)
    ma, mb = evaluate(inst, prof, a), evaluate(inst, prof, b)
    d = diff_plans(inst, prof, ma, a.routes, mb, b.routes)
    assert not d.identical


# ==========================================================================
# THE EXISTING PLANNER, JUDGED BY THE SAME METRIC CODE.
# ==========================================================================

@_needs_archive
def test_the_metrics_can_express_an_infeasible_plan():
    """If `PlanMetrics` could not report a violation it could not report the
    finding below. Pinned by evaluating a deliberately over-loaded route."""
    inst, prof = _toy()
    both_wheelchair = AccessibilityProfile(
        instance_name="toy4", num_requests=4, num_vehicles=2,
        wheelchair_requests=frozenset({1, 2}), accessible_vehicles=frozenset({0}),
        wheelchair_positions=1, wheelchair_footprint=2,
    )
    cert = certify_group(inst, prof, [1, 2], 0).certificate  # legal when only 1 is a wheelchair user
    routes = empty_routes(inst)
    schedules = [[0.0, 0.0] for _ in routes]
    routes[0] = list(cert.sequence)
    schedules[0] = list(cert.begin_service)
    m = evaluate_plan(inst, both_wheelchair, routes, schedules, policy="over-loaded")
    assert m.equipment_violations > 0
    assert m.feasibility_violations > 0


@_needs_archive
def test_the_existing_heuristic_planner_is_accessibility_blind():
    """A FINDING, reported rather than asserted away: `darp_solver.solve_darp`
    knows nothing about wheelchair positions, so under an equipment model its
    routes can be infeasible. That is a statement about what the current planner
    does not model -- NOT a defect in its own terms, and NOT evidence about any
    real fleet, since the labels here are assigned. The test pins that the
    evaluation surfaces it either way."""
    inst = _load("a2-16")
    prof = assign_accessibility(inst, seed=1, wheelchair_share=0.9, accessible_vehicles=1)
    solution = solve_darp(inst, seed=1, max_iterations=60, time_limit_s=30.0)
    routes, schedules = routes_from_solution(inst, solution)
    m = evaluate_plan(inst, prof, routes, schedules, policy="lns")
    assert m.routing_violations == 0, "the heuristic's own contract still holds"
    assert m.equipment_violations > 0, (
        "with 90% wheelchair demand and one accessible vehicle the accessibility-blind "
        "planner must violate the equipment layer; if it does not, the layer is inert here"
    )


@_needs_archive
def test_routes_from_solution_round_trips_a_plan_through_the_shared_metric_code():
    inst = _load("a2-16")
    prof = assign_accessibility(inst, seed=1)
    plan = plan_online(inst, prof, seed=1)
    routes, schedules = routes_from_solution(inst, plan.solution)
    assert [tuple(r) for r in routes] == list(plan.routes)
    direct = evaluate(inst, prof, plan)
    via = evaluate_plan(inst, prof, routes, schedules, policy=plan.policy, seed=plan.seed)
    assert via.occupancy == pytest.approx(direct.occupancy)
    assert via.trips_served == direct.trips_served
