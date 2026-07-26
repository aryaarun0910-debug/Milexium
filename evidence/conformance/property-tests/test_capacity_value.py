"""Program F conformance: future capacity value, and the honesty of the estimate.

FOUR CLAIMS ARE ON TRIAL.

1. **NO LOOKAHEAD.** The prior is a function of the OBSERVED requests and nothing
   else. Tested in its observable form: two runs whose observed prefix agrees
   produce byte-identical priors and scenario draws however violently their
   unobserved remainder differs. A capacity estimate that could see the future
   would make the whole measurement a re-labelled offline planner.

2. **THE FEASIBILITY HALF IS REAL EVEN THOUGH THE DEMAND HALF IS NOT.** A
   scenario trip counts as reachable only when two independent checkers accept a
   concrete schedule for it. So an accessible scenario is unreachable on a
   vehicle with no wheelchair position -- tested directly, because if the spliced
   instance quietly lost the equipment layer, the accessible foreclosure number
   would be measuring nothing.

3. **THE INCREMENTAL SHORTCUT EQUALS THE DEFINITION.** `reach_with_replacement`
   and `value_of_replacement` exist because the honest computation is too slow to
   run inside a planning loop. A shortcut that silently disagreed with what it
   shortcuts would be worse than no shortcut, so equality is pinned rather than
   argued.

4. **MONOTONICITY.** Committing more work to a fleet never increases what it can
   still absorb. That makes foreclosure non-negative, which is the only reason it
   can be read as a cost at all.

The instances are hand-built or from the acquired Cordeau set, the accessibility
labels are ASSIGNED, and the scenario prior is a stated placeholder rather than a
demand model. Everything here supports ALGORITHMIC claims only.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.decide.capacity_value import (
    CapacityValue,
    attach_capacity_features,
    build_ensemble,
    build_lens,
    empty_routes,
    prior_from_observed,
    sample_scenarios,
)
from app.decide.compatibility import (
    AccessibilityProfile,
    admits_insertion,
    assign_accessibility,
    build_compatibility_graph,
    certify_group,
)
from app.decide.darp_ir import DarpInstance, DarpNode
from app.decide.darp_loader import find_benchmark_archive, load_zip_instance

_ARCHIVE = find_benchmark_archive()
_needs_archive = pytest.mark.skipif(_ARCHIVE is None, reason="Cordeau DARP benchmark archive not acquired")


def _toy(*, capacity: int = 3, vehicles: int = 2) -> DarpInstance:
    def node(i, x, y, load, tw=(0.0, 900.0)):
        return DarpNode(node_id=i, x=x, y=y, service_duration=0.0, load=load, tw_start=tw[0], tw_end=tw[1])

    n = 6
    nodes = [node(0, 0.0, 0.0, 0)]
    for r in range(1, n + 1):
        nodes.append(node(r, float(r), 0.0, 1))
    for r in range(1, n + 1):
        nodes.append(node(n + r, float(r) + 8.0, 0.0, -1))
    nodes.append(node(2 * n + 1, 0.0, 0.0, 0))
    return DarpInstance.build(
        name="toy6", num_vehicles=vehicles, num_requests=n, max_route_duration=900.0,
        vehicle_capacity=capacity, max_ride_time=400.0, nodes=nodes,
    )


def _profile(wheelchair: set[int], *, accessible: int = 1, n: int = 6, vehicles: int = 2):
    return AccessibilityProfile(
        instance_name="toy6", num_requests=n, num_vehicles=vehicles,
        wheelchair_requests=frozenset(wheelchair),
        accessible_vehicles=frozenset(range(accessible)),
        wheelchair_positions=1, wheelchair_footprint=2,
    )


def _footprint_toy() -> tuple[DarpInstance, AccessibilityProfile]:
    """A fleet of two, one accessible, where the SHARED FLOOR is what bites.

    Requests 1 and 2 are ambulatory and ride nearly the whole shift, so a vehicle
    carrying both has one seat-equivalent free -- not enough to deploy a station,
    which costs two. Request 3 is a wheelchair rider with a tight midday window,
    and the scenario prior is fitted on it alone, so every hypothetical future
    trip needs an accessible vehicle at exactly the time the ambulatory pair is
    aboard. That is the situation the packet is about, reduced to something a
    reader can check by hand.
    """
    def nd(i, x, y, load, tw):
        return DarpNode(node_id=i, x=x, y=y, service_duration=0.0, load=load, tw_start=tw[0], tw_end=tw[1])

    shift = (0.0, 100.0)
    nodes = [
        nd(0, 0.0, 0.0, 0, shift),
        nd(1, 1.0, 0.0, 1, (0.0, 5.0)),
        nd(2, 3.0, 0.0, 1, (0.0, 5.0)),
        nd(3, 20.0, 0.0, 1, (40.0, 45.0)),
        nd(4, 2.0, 0.0, -1, (88.0, 100.0)),
        nd(5, 4.0, 0.0, -1, (88.0, 100.0)),
        nd(6, 22.0, 0.0, -1, (40.0, 100.0)),
        nd(7, 0.0, 0.0, 0, shift),
    ]
    instance = DarpInstance.build(
        name="footprint", num_vehicles=2, num_requests=3, max_route_duration=100.0,
        vehicle_capacity=3, max_ride_time=100.0, nodes=nodes,
    )
    profile = AccessibilityProfile(
        instance_name="footprint", num_requests=3, num_vehicles=2,
        wheelchair_requests=frozenset({3}), accessible_vehicles=frozenset({0}),
        wheelchair_positions=1, wheelchair_footprint=2,
    )
    return instance, profile


# ==========================================================================
# 1. NO LOOKAHEAD.
# ==========================================================================

def test_the_prior_depends_only_on_the_observed_requests():
    """Change the unobserved half of the world completely; the prior does not
    move. This is the testable form of "the planner cannot see the future"."""
    inst = _toy()
    seen = [1, 2, 3]
    a = prior_from_observed(inst, _profile({1, 5, 6}), seen)
    b = prior_from_observed(inst, _profile({1, 4}), seen)
    assert a == b


def test_the_scenario_draw_depends_only_on_the_observed_requests():
    inst = _toy()
    seen = [1, 2, 3]
    a = sample_scenarios(inst, prior_from_observed(inst, _profile({1, 5}), seen), 8, seed=4)
    b = sample_scenarios(inst, prior_from_observed(inst, _profile({1, 6}), seen), 8, seed=4)
    assert a == b


def test_the_prior_has_no_parameter_through_which_the_future_could_enter():
    """Structural, so a later signature change has to argue with a failing test.
    `observed` is the only request-level input."""
    import inspect

    params = set(inspect.signature(prior_from_observed).parameters)
    assert params == {"instance", "profile", "observed", "jitter_fraction", "max_time_shift"}


def test_a_prior_needs_something_to_resample():
    inst = _toy()
    with pytest.raises(ValueError):
        prior_from_observed(inst, _profile(set()), [])


def test_the_prior_records_how_little_it_was_fitted_on():
    inst = _toy()
    prior = prior_from_observed(inst, _profile({1}), [1])
    assert prior.observed == (1,)
    assert "PLACEHOLDER PRIOR" in prior.note


def test_scenario_sampling_is_reproducible_from_its_seed():
    inst = _toy()
    prior = prior_from_observed(inst, _profile({1, 2}), [1, 2, 3])
    assert sample_scenarios(inst, prior, 6, seed=11) == sample_scenarios(inst, prior, 6, seed=11)
    assert sample_scenarios(inst, prior, 6, seed=11) != sample_scenarios(inst, prior, 6, seed=12)


# ==========================================================================
# 2. THE SPLICED INSTANCE KEEPS BOTH CHECKERS.
# ==========================================================================

def test_splicing_scenarios_does_not_move_the_real_nodes():
    """Every distance between two base nodes must survive the re-indexing. If it
    did not, the reachability question would be asked about a different instance
    than the one being planned."""
    inst = _toy()
    prof = _profile({1})
    prior = prior_from_observed(inst, prof, [1, 2, 3])
    lens = build_lens(inst, prof, prior, scenarios=5, seed=0)
    for i in range(2 * inst.num_requests + 2):
        for j in range(2 * inst.num_requests + 2):
            assert lens.extended.dist(lens.remap[i], lens.remap[j]) == pytest.approx(inst.dist(i, j))


def test_the_extended_profile_keeps_the_real_accessibility_labels():
    inst = _toy()
    prof = _profile({1, 3})
    lens = build_lens(inst, prof, prior_from_observed(inst, prof, [1, 2, 3]), scenarios=5, seed=0)
    for r in (1, 3):
        assert lens.extended_profile.needs_wheelchair(r)
    for r in (2, 4, 5, 6):
        assert not lens.extended_profile.needs_wheelchair(r)


def test_an_accessible_scenario_trip_is_unreachable_on_a_vehicle_with_no_position():
    """The equipment layer survives the splice. Without this the accessible
    foreclosure count would be indistinguishable from the total one."""
    inst = _toy()
    prof = _profile({1, 2, 3, 4, 5, 6}, accessible=1)  # everyone needs a position
    prior = prior_from_observed(inst, prof, [1, 2, 3])
    lens = build_lens(inst, prof, prior, scenarios=6, seed=0)
    assert lens.accessible_scenario_ids(), "vacuous: no accessible scenarios drawn"
    empty = [0, lens.extended.depot_end]
    for s in lens.accessible_scenario_ids():
        assert not admits_insertion(lens.extended, lens.extended_profile, 1, empty, s)
        assert admits_insertion(lens.extended, lens.extended_profile, 0, empty, s)


# ==========================================================================
# 3. THE INCREMENTAL SHORTCUT EQUALS THE DEFINITION.
# ==========================================================================

@_needs_archive
def test_reach_with_replacement_equals_reach_on_the_replaced_fleet():
    inst = load_zip_instance(_ARCHIVE, "a2-16")
    prof = assign_accessibility(inst, seed=1)
    prior = prior_from_observed(inst, prof, range(1, 9))
    lens = build_lens(inst, prof, prior, scenarios=8, seed=2)
    routes = empty_routes(inst)
    matrix = lens.reach_matrix(routes)
    for r in (1, 3, 7):
        cert = certify_group(inst, prof, [r], 0).certificate
        after = [list(s) for s in routes]
        after[0] = list(cert.sequence)
        assert lens.reach_with_replacement(matrix, 0, cert.sequence) == lens.reach(after)


@_needs_archive
def test_value_of_replacement_equals_the_full_value_of_definition():
    inst = load_zip_instance(_ARCHIVE, "a2-16")
    prof = assign_accessibility(inst, seed=1)
    prior = prior_from_observed(inst, prof, range(1, 9))
    ens = build_ensemble(inst, prof, prior, draws=3, scenarios=8, seed=5)
    routes = empty_routes(inst)
    snap = ens.snapshot(routes)
    for r in (2, 5):
        cert = certify_group(inst, prof, [r], 0).certificate
        after = [list(s) for s in routes]
        after[0] = list(cert.sequence)
        fast = ens.value_of_replacement(snap, 0, cert.sequence)
        slow = ens.value_of(routes, after)
        assert fast.trips_foreclosed == pytest.approx(slow.trips_foreclosed)
        assert fast.accessible_trips_foreclosed == pytest.approx(slow.accessible_trips_foreclosed)
        assert fast.reach_before == pytest.approx(slow.reach_before)
        assert fast.reach_after == pytest.approx(slow.reach_after)


def test_reach_from_a_matrix_equals_the_short_circuiting_reach():
    inst = _toy()
    prof = _profile({1, 2})
    lens = build_lens(inst, prof, prior_from_observed(inst, prof, [1, 2, 3]), scenarios=6, seed=1)
    routes = empty_routes(inst)
    assert lens.reach_from(lens.reach_matrix(routes)) == lens.reach(routes)


# ==========================================================================
# 4. MONOTONICITY, and therefore foreclosure as a cost.
# ==========================================================================

@_needs_archive
def test_committing_work_never_increases_what_the_fleet_can_still_absorb():
    inst = load_zip_instance(_ARCHIVE, "a2-16")
    prof = assign_accessibility(inst, seed=1)
    prior = prior_from_observed(inst, prof, range(1, 9))
    lens = build_lens(inst, prof, prior, scenarios=10, seed=3)
    routes = empty_routes(inst)
    before = lens.reach(routes)
    for r in (1, 2, 3, 4):
        cert = certify_group(inst, prof, [r], 0).certificate
        routes[0] = list(cert.sequence)
        now = lens.reach(routes)
        assert now[0] <= before[0]
        assert now[1] <= before[1]
        before = now


@_needs_archive
def test_foreclosure_is_never_negative_and_accessible_never_exceeds_total():
    inst = load_zip_instance(_ARCHIVE, "a2-16")
    prof = assign_accessibility(inst, seed=1)
    prior = prior_from_observed(inst, prof, range(1, 9))
    ens = build_ensemble(inst, prof, prior, draws=3, scenarios=8, seed=6)
    routes = empty_routes(inst)
    snap = ens.snapshot(routes)
    for r in range(1, 9):
        out = certify_group(inst, prof, [r], 0)
        if not out.certified:
            continue
        v = ens.value_of_replacement(snap, 0, out.certificate.sequence)
        assert v.trips_foreclosed >= -1e-9
        assert v.accessible_trips_foreclosed <= v.trips_foreclosed + 1e-9
        assert v.accessible_trips_foreclosed >= -1e-9


def test_an_empty_fleet_has_the_greatest_reach_of_any_state():
    inst = _toy()
    prof = _profile({1})
    lens = build_lens(inst, prof, prior_from_observed(inst, prof, [1, 2, 3]), scenarios=8, seed=0)
    empty = empty_routes(inst)
    best = lens.reach(empty)
    cert = certify_group(inst, prof, [1, 2], 0).certificate
    loaded = [list(s) for s in empty]
    loaded[0] = list(cert.sequence)
    assert lens.reach(loaded)[0] <= best[0]


# ==========================================================================
# THE ESTIMATE IS AN ESTIMATE, AND SAYS SO.
# ==========================================================================

def test_a_single_draw_reports_zero_standard_error_and_several_draws_can_report_more():
    inst = _toy()
    prof = _profile({1})
    prior = prior_from_observed(inst, prof, [1, 2, 3])
    routes = empty_routes(inst)
    cert = certify_group(inst, prof, [1, 2], 0).certificate
    after = [list(s) for s in routes]
    after[0] = list(cert.sequence)
    one = build_ensemble(inst, prof, prior, draws=1, scenarios=8, seed=0).value_of(routes, after)
    assert one.draws == 1 and one.stderr == 0.0
    many = build_ensemble(inst, prof, prior, draws=6, scenarios=8, seed=0).value_of(routes, after)
    assert many.draws == 6 and many.stderr >= 0.0


def test_distinguishable_from_is_pinned_in_both_directions():
    """A predicate only ever asserted True is a constant, and ADR-0060 records
    exactly that mistake surviving a mutation. Both directions here."""
    def value(mean: float, err: float) -> CapacityValue:
        return CapacityValue(
            draws=4, scenarios_per_draw=8, accessible_scenarios_per_draw=2.0,
            reach_before=8.0, reach_after=8.0 - mean,
            accessible_reach_before=2.0, accessible_reach_after=2.0,
            trips_foreclosed=mean, accessible_trips_foreclosed=0.0,
            stderr=err, accessible_stderr=err, per_draw=(),
        )

    assert value(3.0, 0.1).distinguishable_from(value(0.0, 0.1))
    assert not value(0.10, 1.0).distinguishable_from(value(0.0, 1.0))
    assert not value(0.0, 0.0).distinguishable_from(value(0.0, 0.0))


def test_the_capacity_record_carries_the_prior_warning():
    inst = _toy()
    prof = _profile({1})
    prior = prior_from_observed(inst, prof, [1, 2])
    routes = empty_routes(inst)
    v = build_ensemble(inst, prof, prior, draws=2, scenarios=4, seed=0).value_of(routes, routes)
    assert "PLACEHOLDER PRIOR" in v.to_record()["prior_note"]
    assert v.trips_foreclosed == 0.0, "a fleet that did not change forecloses nothing"


def test_an_ensemble_needs_at_least_one_draw():
    inst = _toy()
    prof = _profile({1})
    with pytest.raises(ValueError):
        build_ensemble(inst, prof, prior_from_observed(inst, prof, [1]), draws=0)


# ==========================================================================
# THE DISCRIMINATING CASE: accessible capacity is not fungible capacity.
# ==========================================================================

def test_burning_the_only_accessible_vehicle_forecloses_accessible_trips_specifically():
    """THE WHOLE PACKET IN ONE TEST. Two ambulatory riders placed on the sole
    accessible vehicle forecloses future WHEELCHAIR trips; the same two riders
    placed on an ordinary vehicle forecloses none. Same riders, same trips, same
    service -- only the seat differs, and the cost lands on somebody else.

    This is the quantity `exposure.attribute_capacity` can only recover after the
    denial has happened, made available at the moment the choice is being made.
    An aggregate foreclosure count would score both placements identically and
    hide exactly the harm this work exists to surface.
    """
    inst, prof = _footprint_toy()
    prior = prior_from_observed(inst, prof, [3])
    assert prior.wheelchair_share == 1.0
    ens = build_ensemble(inst, prof, prior, draws=3, scenarios=6, seed=0)
    routes = empty_routes(inst)
    snap = ens.snapshot(routes)
    assert snap.accessible_reach_before > 0, "vacuous: no accessible scenario reachable to begin with"

    cert = certify_group(inst, prof, [1, 2], 0).certificate
    on_accessible = ens.value_of_replacement(snap, 0, cert.sequence)
    on_ordinary = ens.value_of_replacement(snap, 1, cert.sequence)
    assert on_accessible.accessible_trips_foreclosed > on_ordinary.accessible_trips_foreclosed
    assert on_ordinary.accessible_trips_foreclosed == 0.0
    # and the two placements are genuinely distinguishable, not sampling noise
    assert on_accessible.distinguishable_from(on_ordinary)


def test_the_footprint_is_what_does_the_blocking_and_not_the_clock():
    """Guard against the discriminating test above passing for the wrong reason.
    Give the same fleet stations that cost one seat-equivalent instead of two and
    the blocking disappears -- so it really is the equipment footprint, not the
    timetable, that forecloses the accessible trips."""
    inst, prof = _footprint_toy()
    roomy = replace(prof, wheelchair_footprint=1)
    prior = prior_from_observed(inst, prof, [3])
    routes = empty_routes(inst)
    cert = certify_group(inst, prof, [1, 2], 0).certificate

    tight_ens = build_ensemble(inst, prof, prior, draws=3, scenarios=6, seed=0)
    roomy_ens = build_ensemble(inst, roomy, prior, draws=3, scenarios=6, seed=0)
    tight = tight_ens.value_of_replacement(tight_ens.snapshot(routes), 0, cert.sequence)
    loose = roomy_ens.value_of_replacement(roomy_ens.snapshot(routes), 0, cert.sequence)
    assert tight.accessible_trips_foreclosed > loose.accessible_trips_foreclosed


@_needs_archive
def test_attach_capacity_features_fills_only_the_estimated_fields():
    """The estimate must never overwrite a measured feature, and an unfilled
    estimate must stay None rather than becoming a computed zero."""
    inst = load_zip_instance(_ARCHIVE, "a2-16")
    prof = assign_accessibility(inst, seed=1)
    graph = build_compatibility_graph(inst, prof, max_group_size=2)
    assert all(e.features.future_capacity_cost is None for e in graph.edges)
    prior = prior_from_observed(inst, prof, range(1, inst.num_requests + 1))
    ens = build_ensemble(inst, prof, prior, draws=2, scenarios=6, seed=0)
    enriched = attach_capacity_features(graph, ens)
    assert len(enriched.edges) == len(graph.edges)
    for before, after in zip(graph.edges, enriched.edges):
        assert after.features.future_capacity_cost is not None
        assert after.certificate == before.certificate
        assert after.features.vehicle_miles == before.features.vehicle_miles
        assert after.features.occupancy == before.features.occupancy
