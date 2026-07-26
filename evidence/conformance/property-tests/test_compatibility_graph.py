"""Program F conformance: the compatibility graph and the authority that fills it.

ONE CLAIM IS ON TRIAL ABOVE ALL OTHERS. **A score can propose; only the authority
can establish.** The suite tests that by attacking it: an adversarial scorer that
ranks infeasible groups highest, a random scorer swept over seeds, a scorer that
returns a constant. If scoring carried any authority the graph would differ
between them. It does not, and the test asserts set equality rather than a count,
because a count would pass while the contents drifted.

THE SECOND CLAIM: a certificate is a PROOF, not a label. `Certificate` cannot be
constructed without the authority's private witness; every certificate carries the
schedule it was proved on; and a certificate whose schedule is tampered with is
rejected on admission to the graph. All three directions are pinned, including the
one that only fails when someone reaches into a private module attribute -- because
"nobody would do that" is not a property.

THE THIRD CLAIM, and the one this repository has got wrong before: the equipment
layer must not be VACUOUS. ADR-0060 records a pairing constraint that was
meaningless at K=1 while every test instance happened to be K=1. So here:
`can_bind` is asserted in BOTH directions, at least one real pair on a real
instance must be rejected by the equipment checker specifically, and the
shared-ride filter that makes equipment contention possible at all is tested by
showing it strictly reduces the edge set.

Instances are hand-built (small enough to check by hand) or from the acquired
Cordeau academic set. Both support ALGORITHMIC claims only, and the accessibility
labels are ASSIGNED by the harness -- the published files carry none.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import replace
from random import Random

import pytest

from app.decide import compatibility as C
from app.decide.compatibility import (
    AccessibilityProfile,
    Certificate,
    ForgedCertificate,
    ProposalView,
    UncertifiedGroup,
    admits_insertion,
    assign_accessibility,
    bound_by_equipment,
    build_compatibility_graph,
    certify_group,
    certify_insertion,
    check_equipment_feasibility,
    geometric_affinity,
    onboard_profile,
    route_passenger_miles,
    route_shared_vehicle_miles,
    shares_a_ride,
    solo_route,
)
from app.decide.darp_ir import DarpInstance, DarpNode
from app.decide.darp_loader import find_benchmark_archive, load_zip_instance
from app.decide.darp_solver import route_distance
from app.decide.feasibility import check_darp_feasibility

_ARCHIVE = find_benchmark_archive()
_needs_archive = pytest.mark.skipif(_ARCHIVE is None, reason="Cordeau DARP benchmark archive not acquired")

# Kept small on purpose: the graph is O(n^2) certifications and the suite runs on
# CI next to two other expensive Program F modules.
_INSTANCES = ("a2-16", "a3-18")


def _load(name: str) -> DarpInstance:
    return load_zip_instance(_ARCHIVE, name)


# ==========================================================================
# A hand-built instance small enough to reason about exactly.
#
# Four requests on a line, all with wide windows, so every pooling question is
# decided by capacity and equipment rather than by timing. Capacity 3 with a
# wheelchair footprint of 2 means: one wheelchair rider plus one ambulatory fits,
# two wheelchair riders do not, and two ambulatory riders do.
# ==========================================================================

def _toy(*, capacity: int = 3, vehicles: int = 2, max_ride: float = 400.0) -> DarpInstance:
    def node(i, x, y, load, tw=(0.0, 900.0)):
        return DarpNode(node_id=i, x=x, y=y, service_duration=0.0, load=load, tw_start=tw[0], tw_end=tw[1])

    n = 4
    nodes = [node(0, 0.0, 0.0, 0)]
    for r in range(1, n + 1):
        nodes.append(node(r, float(r), 0.0, 1))
    for r in range(1, n + 1):
        nodes.append(node(n + r, float(r) + 10.0, 0.0, -1))
    nodes.append(node(2 * n + 1, 0.0, 0.0, 0))
    return DarpInstance.build(
        name="toy4",
        num_vehicles=vehicles,
        num_requests=n,
        max_route_duration=900.0,
        vehicle_capacity=capacity,
        max_ride_time=max_ride,
        nodes=nodes,
    )


def _simultaneous() -> DarpInstance:
    """Three requests that MUST all be aboard at once: every pickup window is the
    same five minutes and every drop-off window the same ten, so no ordering can
    stagger them. Needed because a chained ordering (A+B, then B+C) keeps the peak
    floor low and would let a group slip past a floor limit it genuinely
    violates."""
    def nd(i, x, y, load, tw):
        return DarpNode(node_id=i, x=x, y=y, service_duration=0.0, load=load, tw_start=tw[0], tw_end=tw[1])

    early, late, shift = (0.0, 5.0), (50.0, 60.0), (0.0, 200.0)
    nodes = [nd(0, 0.0, 0.0, 0, shift)]
    for r in range(1, 4):
        nodes.append(nd(r, float(r), 0.0, 1, early))
    for r in range(1, 4):
        nodes.append(nd(3 + r, float(r) + 20.0, 0.0, -1, late))
    nodes.append(nd(7, 0.0, 0.0, 0, shift))
    return DarpInstance.build(
        name="simul", num_vehicles=1, num_requests=3, max_route_duration=200.0,
        vehicle_capacity=3, max_ride_time=200.0, nodes=nodes,
    )


def _toy_profile(wheelchair: set[int], *, accessible: int = 1, positions: int = 1, footprint: int = 2):
    return AccessibilityProfile(
        instance_name="toy4",
        num_requests=4,
        num_vehicles=2,
        wheelchair_requests=frozenset(wheelchair),
        accessible_vehicles=frozenset(range(accessible)),
        wheelchair_positions=positions,
        wheelchair_footprint=footprint,
    )


# ==========================================================================
# THE AUTHORITY: a certificate is a proof, not a label.
# ==========================================================================

def test_a_certificate_cannot_be_constructed_without_the_authoritys_witness():
    with pytest.raises(UncertifiedGroup):
        Certificate(
            request_ids=(1, 2),
            vehicle=0,
            sequence=(0, 1, 2, 5, 6, 9),
            begin_service=(0.0, 1.0, 2.0, 3.0, 4.0, 5.0),
            checked_by=("i", "say", "so"),
        )


def test_a_certificate_cannot_be_forged_with_a_wrong_witness_object():
    with pytest.raises(UncertifiedGroup):
        Certificate(
            request_ids=(1,),
            vehicle=0,
            sequence=(0, 1, 5, 9),
            begin_service=(0.0, 1.0, 2.0, 3.0),
            checked_by=(),
            witness=object(),
        )


def test_every_certificate_names_both_independent_checkers():
    inst, prof = _toy(), _toy_profile(set())
    out = certify_group(inst, prof, [1, 2], 0)
    assert out.certified
    assert out.certificate.checked_by == (
        "feasibility.check_darp_feasibility",
        "compatibility.check_equipment_feasibility",
    )


def test_a_certificates_witness_schedule_survives_re_derivation_from_the_raw_instance():
    inst, prof = _toy(), _toy_profile({1})
    out = certify_group(inst, prof, [1, 2], 0)
    assert out.certified
    assert out.certificate.recheck(inst, prof) == []


def test_a_tampered_witness_schedule_fails_recheck():
    """The schedule is the proof. Move it and the proof stops holding -- which is
    the whole reason the certificate carries it rather than a boolean."""
    inst, prof = _toy(), _toy_profile(set())
    cert = certify_group(inst, prof, [1, 2], 0).certificate
    tampered = Certificate(
        request_ids=cert.request_ids,
        vehicle=cert.vehicle,
        sequence=cert.sequence,
        begin_service=tuple(b - 500.0 for b in cert.begin_service),
        checked_by=cert.checked_by,
        witness=C._WITNESS,
    )
    assert tampered.recheck(inst, prof) != []


def test_the_graph_rejects_a_forged_certificate_on_admission(monkeypatch):
    """Reaching into the private witness is the only way to forge one, and it does
    not work: the graph re-runs both checkers before admitting anything, so a
    forgery is not merely discouraged, it is rejected."""
    inst, prof = _toy(), _toy_profile(set())
    real = certify_group(inst, prof, [1, 2], 0).certificate

    def forged(*_a, **_k):
        bad = Certificate(
            request_ids=(1, 2),
            vehicle=0,
            sequence=real.sequence,
            begin_service=tuple(b - 1000.0 for b in real.begin_service),
            checked_by=real.checked_by,
            witness=C._WITNESS,
        )
        return C.CertificationOutcome(
            request_ids=(1, 2), vehicle=0, certificate=bad, sequences_tried=1,
            rejected_by=(), violations=(), detail="forged",
        )

    monkeypatch.setattr(C, "certify_group", forged)
    with pytest.raises(ForgedCertificate):
        build_compatibility_graph(inst, prof, max_group_size=2)


def test_the_routing_checker_inside_the_authority_is_live_not_decorative():
    """`exact_schedule` is exact, so on this codebase the routing checker never
    actually rejects anything it produces -- which means removing it from the
    authority would pass every other test in this file. That is precisely the
    shape of vacuity ADR-0060 found (a constraint no instance exercised), so the
    gate is exercised DIRECTLY here: hand `_mint` a schedule the routing checker
    must refuse and require it to refuse.

    Defence in depth is the point of the second checker -- it is what would catch
    a future bug in the scheduler -- and a defence nothing tests is prose.
    """
    inst, prof = _toy(), _toy_profile(set())
    good = certify_group(inst, prof, [1, 2], 0).certificate
    broken = [b - 400.0 for b in good.begin_service]  # violates travel-time consistency
    cert, rejected, violations = C._mint(inst, prof, (1, 2), 0, good.sequence, broken)
    assert cert is None
    assert "feasibility.check_darp_feasibility" in rejected
    assert violations


def test_the_position_count_refuses_a_pair_that_the_floor_alone_would_allow():
    """Isolates the two halves of the equipment layer. With a footprint of ONE
    seat-equivalent, two wheelchair riders fit the floor of a three-seat vehicle
    perfectly well -- and are still refused, because the vehicle has one position.
    Without this the positions check could be deleted and the floor check would
    cover for it."""
    inst = _toy()
    one_position = _toy_profile({1, 2}, footprint=1, positions=1)
    assert sum(one_position.floor_units(inst, r) for r in (1, 2)) <= inst.vehicle_capacity
    assert not certify_group(inst, one_position, [1, 2], 0).certified
    two_positions = _toy_profile({1, 2}, footprint=1, positions=2)
    assert certify_group(inst, two_positions, [1, 2], 0).certified


def test_the_shared_floor_refuses_a_group_the_positions_and_the_load_sweep_both_allow():
    """The other half of the isolation, and it was found by a SURVIVING mutation:
    deleting the floor check entirely left every test in this file green, because
    the position count happened to refuse the same groups.

    The case that separates them: ONE wheelchair rider (one position, fine) plus
    two ambulatory riders. The instance's own integer load sweep counts three
    riders against a capacity of three and allows it. The floor counts a deployed
    station at two seat-equivalents -- four in total -- and refuses. If the floor
    check were removed, this group would be certified and a real vehicle could not
    carry it.
    """
    inst = _simultaneous()
    prof = AccessibilityProfile(
        instance_name="simul", num_requests=3, num_vehicles=1,
        wheelchair_requests=frozenset({1}), accessible_vehicles=frozenset({0}),
        wheelchair_positions=1, wheelchair_footprint=2,
    )
    group = [1, 2, 3]
    # the raw routing checker, which knows nothing about stations, is happy
    permissive = replace(prof, wheelchair_requests=frozenset())
    ok = certify_group(inst, permissive, group, 0)
    assert ok.certified, "fixture broken: the group must be routable before equipment is applied"
    probe = C._probe(inst, ok.certificate.as_route())
    assert check_darp_feasibility(inst, probe) == []
    # one wheelchair rider fits the single position ...
    assert sum(1 for r in group if prof.needs_wheelchair(r)) <= prof.wheelchair_positions
    # ... and the shared floor still refuses the group
    assert sum(prof.floor_units(inst, r) for r in group) > inst.vehicle_capacity
    assert not certify_group(inst, prof, group, 0).certified
    assert bound_by_equipment(inst, prof, probe)
    # positive control: drop one ambulatory rider and the floor fits again
    assert certify_group(inst, prof, [1, 2], 0).certified


def test_certify_group_refuses_a_malformed_group():
    inst, prof = _toy(), _toy_profile(set())
    with pytest.raises(ValueError):
        certify_group(inst, prof, [], 0)
    with pytest.raises(ValueError):
        certify_group(inst, prof, [1, 1], 0)
    with pytest.raises(ValueError):
        certify_group(inst, prof, [99], 0)


# ==========================================================================
# THE SEPARATION: a scorer proposes, it never establishes.
# ==========================================================================

def _adversarial(view: ProposalView) -> float:
    """Score every group that CANNOT fit as highly as possible, and everything
    else as low as possible. If a score carried any authority this would fill the
    graph with garbage."""
    return math.inf if sum(view.floor_units) > view.vehicle_capacity else -math.inf


def _constant(view: ProposalView) -> float:
    return 1.0


def _seeded_random(seed: int):
    rng = Random(seed)

    def scorer(view: ProposalView) -> float:
        return rng.random()

    return scorer


@_needs_archive
@pytest.mark.parametrize("name", _INSTANCES)
def test_the_order_2_graph_is_identical_under_an_adversarial_scorer(name):
    """THE load-bearing test of the packet's central design claim. Every pair is
    offered to the authority regardless of score, so the certified edge set cannot
    depend on the scorer. Asserted as SET equality -- a count would pass while the
    contents drifted."""
    inst = _load(name)
    prof = assign_accessibility(inst, seed=1)
    default = build_compatibility_graph(inst, prof, max_group_size=2)
    attacked = build_compatibility_graph(inst, prof, scorer=_adversarial, max_group_size=2)
    assert {e.request_ids for e in default.edges} == {e.request_ids for e in attacked.edges}
    assert default.edges, "vacuous: no edges to compare"


@_needs_archive
@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_the_order_2_graph_is_identical_under_random_scorers(seed):
    inst = _load("a2-16")
    prof = assign_accessibility(inst, seed=1)
    reference = build_compatibility_graph(inst, prof, max_group_size=2)
    shuffled = build_compatibility_graph(inst, prof, scorer=_seeded_random(seed), max_group_size=2)
    assert {e.request_ids for e in reference.edges} == {e.request_ids for e in shuffled.edges}


@_needs_archive
def test_the_certificates_are_identical_under_a_different_scorer_not_merely_the_edge_set():
    """Same edges is not enough: the SEQUENCE a share is certified on must not
    depend on the scorer either, or the features would silently drift."""
    inst = _load("a2-16")
    prof = assign_accessibility(inst, seed=1)
    a = {e.request_ids: e.certificate.sequence for e in build_compatibility_graph(inst, prof).edges}
    b = {
        e.request_ids: e.certificate.sequence
        for e in build_compatibility_graph(inst, prof, scorer=_constant).edges
    }
    assert a == b and a


def test_a_proposal_view_cannot_express_a_feasibility_verdict():
    """Structural, not stylistic: if the scorer's input type had a field a
    verdict could be written into, the separation would be a convention. It does
    not, and this pins the field list so a later addition has to argue with a
    failing test."""
    fields = set(ProposalView.__dataclass_fields__)
    for forbidden in ("certificate", "feasible", "violations", "schedule", "begin_service", "witness"):
        assert forbidden not in fields
    assert fields == {
        "instance_name", "request_ids", "vehicle", "vehicle_is_accessible", "needs_wheelchair",
        "pickup_xy", "dropoff_xy", "pickup_window", "dropoff_window", "direct_minutes",
        "max_ride_time", "vehicle_capacity", "floor_units",
    }


# ==========================================================================
# EQUIPMENT IS NOT FUNGIBLE -- and the layer is not vacuous.
# ==========================================================================

def test_two_ambulatory_riders_share_where_two_wheelchair_riders_cannot():
    """The same two requests, the same vehicle, the same timing -- only the
    mobility labels differ. Capacity 3 with a footprint of 2 means two stations
    need 4 seat-equivalents, and there is only one position anyway."""
    inst = _toy()
    assert certify_group(inst, _toy_profile(set()), [1, 2], 0).certified
    assert not certify_group(inst, _toy_profile({1, 2}), [1, 2], 0).certified


def test_a_wheelchair_and_an_ambulatory_rider_do_share():
    inst = _toy()
    out = certify_group(inst, _toy_profile({1}), [1, 2], 0)
    assert out.certified
    assert out.certificate.recheck(inst, _toy_profile({1})) == []


def test_a_wheelchair_rider_cannot_ride_a_vehicle_with_no_position():
    inst = _toy()
    prof = _toy_profile({1}, accessible=1)  # vehicle 0 accessible, vehicle 1 not
    assert certify_group(inst, prof, [1], 0).certified
    assert not certify_group(inst, prof, [1], 1).certified


def test_the_equipment_layer_is_the_sole_reason_a_share_is_refused():
    """`bound_by_equipment` is the witness that the layer is doing work rather
    than riding along behind the routing checker: the routing checker accepts this
    exact schedule and the equipment checker does not."""
    inst = _toy()
    ok = certify_group(inst, _toy_profile(set()), [1, 2], 0).certificate
    probe = C._probe(inst, ok.as_route())
    assert check_darp_feasibility(inst, probe) == []
    assert bound_by_equipment(inst, _toy_profile({1, 2}), probe)


def test_can_bind_is_false_when_the_equipment_layer_is_genuinely_inert():
    """The anti-vacuity guard, pinned in the direction that matters. A fleet whose
    stations sit in dedicated floor space, on an all-accessible fleet with as many
    positions as seats, cannot forbid anything the raw checker allows -- and the
    profile says so instead of quietly implying contention that is not there."""
    inst = _toy()
    inert = AccessibilityProfile(
        instance_name="toy4", num_requests=4, num_vehicles=2,
        wheelchair_requests=frozenset({1, 2}),
        accessible_vehicles=frozenset({0, 1}),
        wheelchair_positions=inst.vehicle_capacity,
        wheelchair_footprint=1,
    )
    assert not inert.can_bind(inst)
    assert certify_group(inst, inert, [1, 2], 0).certified


def test_can_bind_is_true_in_each_of_the_three_ways_the_layer_can_bite():
    inst = _toy()
    # (a) a vehicle with no position at all
    assert _toy_profile({1}, accessible=1).can_bind(inst)
    # (b) positions scarcer than seats
    assert AccessibilityProfile(
        instance_name="toy4", num_requests=4, num_vehicles=2, wheelchair_requests=frozenset({1}),
        accessible_vehicles=frozenset({0, 1}), wheelchair_positions=1, wheelchair_footprint=1,
    ).can_bind(inst)
    # (c) a station bigger than the seat it replaces
    assert AccessibilityProfile(
        instance_name="toy4", num_requests=4, num_vehicles=2, wheelchair_requests=frozenset({1}),
        accessible_vehicles=frozenset({0, 1}), wheelchair_positions=inst.vehicle_capacity,
        wheelchair_footprint=2,
    ).can_bind(inst)
    # and false with no wheelchair demand at all
    assert not _toy_profile(set()).can_bind(inst)


def test_no_wheelchair_demand_means_no_equipment_layer_effect():
    inst, prof = _toy(), _toy_profile(set())
    assert not prof.can_bind(inst)
    for group in ([1, 2], [1, 2, 3]):
        out = certify_group(inst, prof, group, 0)
        if out.certified:
            assert check_equipment_feasibility(inst, prof, C._probe(inst, out.certificate.as_route())) == []


@_needs_archive
@pytest.mark.parametrize("name", _INSTANCES)
def test_the_equipment_checker_rejects_real_pairs_on_real_instances(name):
    """NOT VACUOUS ON THE ACTUAL BENCHMARK DATA. ADR-0060 records a constraint
    that was inert because every test instance avoided the case it existed for.
    This asserts the equipment checker refused at least one genuine pair here."""
    inst = _load(name)
    prof = assign_accessibility(inst, seed=1)
    graph = build_compatibility_graph(inst, prof, max_group_size=2)
    rejections = dict(graph.rejections_by_checker)
    assert graph.equipment_layer_can_bind
    assert rejections["compatibility.check_equipment_feasibility"] > 0


@_needs_archive
def test_relabelling_the_accessibility_changes_which_pairs_are_certified():
    """The stratification discriminates. If it did not, every stratified number
    in the packet would be decoration."""
    inst = _load("a2-16")
    none_wc = build_compatibility_graph(inst, assign_accessibility(inst, seed=1, wheelchair_share=0.0))
    lots_wc = build_compatibility_graph(inst, assign_accessibility(inst, seed=1, wheelchair_share=0.9))
    assert {e.request_ids for e in lots_wc.edges} < {e.request_ids for e in none_wc.edges}


# ==========================================================================
# SHARING vs CONSOLIDATION.
# ==========================================================================

def test_shares_a_ride_rejects_back_to_back_service():
    inst = _toy()
    sequential = [0, 1, 5, 2, 6, 9]  # pickup 1, drop 1, pickup 2, drop 2
    assert not shares_a_ride(inst, sequential, [1, 2])


def test_shares_a_ride_accepts_overlapping_riders():
    inst = _toy()
    assert shares_a_ride(inst, [0, 1, 2, 5, 6, 9], [1, 2])


def test_shares_a_ride_accepts_a_chain_through_a_common_rider():
    """A+B then B+C is a genuinely pooled ride even though A and C never meet.
    Requiring ALL pairs to overlap would reject it and understate real pooling."""
    inst = _toy()
    seq = [0, 1, 2, 5, 3, 6, 7, 9]  # 1&2 together, then 2&3 together
    assert shares_a_ride(inst, seq, [1, 2, 3])


def test_shares_a_ride_rejects_three_disjoint_trips():
    inst = _toy()
    assert not shares_a_ride(inst, [0, 1, 5, 2, 6, 3, 7, 9], [1, 2, 3])


def test_a_single_request_trivially_shares():
    assert shares_a_ride(_toy(), [0, 1, 5, 9], [1])


@_needs_archive
def test_requiring_a_shared_ride_strictly_narrows_the_graph():
    """The filter does work: consolidation-only sequences exist on this instance
    and are excluded. Without this the graph would measure route consolidation
    while claiming to measure pooling -- and the equipment layer would be inert,
    because riders never aboard together never contend for a position."""
    inst = _load("a2-16")
    prof = assign_accessibility(inst, seed=1)
    pooled = build_compatibility_graph(inst, prof, max_group_size=2)
    consolidated = build_compatibility_graph(inst, prof, max_group_size=2, require_shared_ride=False)
    p = {e.request_ids for e in pooled.edges}
    c = {e.request_ids for e in consolidated.edges}
    assert p < c, "the shared-ride filter excluded nothing; it is not being exercised"


# ==========================================================================
# FEATURES are re-derived from the witness and mean what they say.
# ==========================================================================

@_needs_archive
@pytest.mark.parametrize("name", _INSTANCES)
def test_every_edge_feature_is_consistent_with_its_own_witness(name):
    inst = _load(name)
    prof = assign_accessibility(inst, seed=1)
    graph = build_compatibility_graph(inst, prof, max_group_size=3)
    assert graph.all_groups
    for edge in graph.all_groups:
        f, seq = edge.features, list(edge.certificate.sequence)
        assert f.vehicle_miles == pytest.approx(route_distance(inst, seq))
        assert f.passenger_miles == pytest.approx(route_passenger_miles(inst, prof, seq))
        assert f.occupancy == pytest.approx(f.passenger_miles / f.vehicle_miles)
        assert f.vehicle_miles_saved == pytest.approx(f.solo_vehicle_miles - f.vehicle_miles)
        assert f.shared_vehicle_miles == pytest.approx(route_shared_vehicle_miles(inst, seq))
        assert f.peak_floor_units <= f.floor_capacity
        assert f.window_slack_consumed_minutes >= -1e-9
        assert f.worst_ride_time_slack_minutes >= -1e-9
        for _r, ride in f.ride_time_minutes:
            assert ride <= inst.max_ride_time + 1e-6
        # a pooled group is pooled: at least one pair aboard together
        assert f.overlapping_pairs >= 1
        assert f.shared_vehicle_miles > 0.0


@_needs_archive
def test_pooling_is_not_free_and_the_features_say_so_in_both_directions():
    """A FINDING, not a formality, and it started life as a wrong assumption in
    this file: "a share never costs more vehicle miles than serving the group
    separately" is FALSE once a genuine shared ride is required.

    Serving A and B on separate depot-anchored trips is always available; a POOLED
    ordering additionally has to keep both riders aboard together, and when their
    origins and destinations are not aligned that detour costs more miles than it
    saves. So `vehicle_miles_saved` goes both ways on real instances, and both
    directions are asserted here -- if it were always positive the metric would be
    measuring something other than what it claims, and if it were always negative
    pooling would have no dividend at all.

    This is precisely why occupancy and vehicle miles must both be reported. A
    planner chasing occupancy alone will happily buy it with miles.
    """
    inst = _load("a2-16")
    prof = assign_accessibility(inst, seed=1)
    saved = [e.features.vehicle_miles_saved for e in build_compatibility_graph(inst, prof, max_group_size=3).all_groups]
    assert saved
    assert any(s > 0 for s in saved), "no share saved any miles; the pooling dividend is absent"
    assert any(s < 0 for s in saved), "every share saved miles; the cost of forced pooling is not exercised"


@_needs_archive
def test_a_pooled_rider_never_travels_less_than_their_direct_distance():
    """The genuine invariant in the neighbourhood of the one above: a rider's
    passenger miles are at least their straight-line trip, because the vehicle's
    path from their pickup to their drop-off cannot be shorter than the direct
    arc. If this ever failed, occupancy would be inflated by a bookkeeping error
    rather than by pooling."""
    inst = _load("a2-16")
    prof = assign_accessibility(inst, seed=1)
    for edge in build_compatibility_graph(inst, prof, max_group_size=3).all_groups:
        direct = sum(
            inst.dist(inst.pickup_index(r), inst.dropoff_index(r)) * prof.riders(inst, r)
            for r in edge.request_ids
        )
        assert edge.features.passenger_miles >= direct - 1e-9


@_needs_archive
def test_added_detour_is_the_difference_between_actual_and_direct_ride_time():
    inst = _load("a2-16")
    prof = assign_accessibility(inst, seed=1)
    for edge in build_compatibility_graph(inst, prof, max_group_size=2).edges:
        f = edge.features
        rides = dict(f.ride_time_minutes)
        directs = dict(f.direct_minutes)
        assert f.added_detour_minutes == pytest.approx(sum(rides[r] - directs[r] for r in rides))
        assert f.added_detour_minutes >= -1e-9


def test_solo_route_and_onboard_profile_agree_on_a_hand_checked_case():
    inst = _toy()
    assert solo_route(inst, 1) == [0, 1, 5, 9]
    # depot -> p1 -> p2 -> d1 -> d2 -> depot : aboard 0,1,2,1,0
    assert onboard_profile(inst, [0, 1, 2, 5, 6, 9]) == [0, 1, 2, 1, 0]


def test_passenger_miles_equal_distance_times_heads_on_a_hand_checked_case():
    inst = _toy()
    prof = _toy_profile(set())
    seq = [0, 1, 2, 5, 6, 9]
    expected = sum(
        inst.dist(a, b) * h
        for (a, b), h in zip(zip(seq, seq[1:]), onboard_profile(inst, seq))
    )
    assert route_passenger_miles(inst, prof, seq) == pytest.approx(expected)


def test_a_wheelchair_riders_footprint_does_not_inflate_passenger_miles():
    """Two seat-equivalents, one passenger. Charging the footprint here would
    inflate the very number the packet is trying to measure honestly."""
    inst = _toy()
    seq = [0, 1, 5, 9]
    assert route_passenger_miles(inst, _toy_profile({1}), seq) == pytest.approx(
        route_passenger_miles(inst, _toy_profile(set()), seq)
    )


# ==========================================================================
# INSERTION: the planner's inner loop uses the same authority.
# ==========================================================================

def test_certify_insertion_returns_the_cheapest_feasible_position():
    """Brute-forced against every position pair, so "cheapest" is checked and not
    asserted."""
    inst, prof = _toy(), _toy_profile(set())
    base = certify_group(inst, prof, [1, 2], 0).certificate
    out = certify_insertion(inst, prof, 0, base.sequence, 3)
    assert out.certified
    best = math.inf
    for pi in range(1, len(base.sequence)):
        with_p = list(base.sequence[:pi]) + [3] + list(base.sequence[pi:])
        for di in range(pi + 1, len(with_p)):
            cand = with_p[:di] + [7] + with_p[di:]
            from app.decide.cpsat_darp import exact_schedule

            begin = exact_schedule(inst, cand)
            if begin is None:
                continue
            probe = C._probe(inst, C.DarpRoute(
                vehicle=0,
                visits=tuple(C.DarpVisit(node_index=s, begin_service=begin[k]) for k, s in enumerate(cand)),
            ))
            if check_darp_feasibility(inst, probe) or check_equipment_feasibility(inst, prof, probe):
                continue
            best = min(best, route_distance(inst, cand))
    assert route_distance(inst, list(out.certificate.sequence)) == pytest.approx(best)


@_needs_archive
def test_admits_insertion_agrees_exactly_with_certify_insertion():
    """The short-circuiting existence check and the cheapest-insertion search must
    never disagree; if they did, the capacity estimate would be counting a
    different feasibility than the planner acts on."""
    inst = _load("a2-16")
    prof = assign_accessibility(inst, seed=1)
    seed_cert = certify_group(inst, prof, [1], 0).certificate
    for r in range(2, 9):
        route = list(seed_cert.sequence)
        assert admits_insertion(inst, prof, 0, route, r) == certify_insertion(
            inst, prof, 0, route, r
        ).certified


def test_certify_insertion_refuses_a_route_that_is_not_depot_anchored():
    inst, prof = _toy(), _toy_profile(set())
    with pytest.raises(ValueError):
        certify_insertion(inst, prof, 0, [1, 5], 2)


def test_certify_insertion_refuses_a_request_already_on_the_route():
    inst, prof = _toy(), _toy_profile(set())
    cert = certify_group(inst, prof, [1], 0).certificate
    with pytest.raises(ValueError):
        certify_insertion(inst, prof, 0, cert.sequence, 1)


def test_insertion_does_not_require_a_shared_ride():
    """Appending a trip a vehicle can reach but not pool with is a legitimate
    placement, and the planner must be able to make it. Only the GRAPH is about
    pooling."""
    inst = _toy(max_ride=15.0)
    prof = _toy_profile(set())
    solo = certify_group(inst, prof, [1], 0).certificate
    out = certify_insertion(inst, prof, 0, solo.sequence, 4)
    assert out.certified


# ==========================================================================
# The graph object.
# ==========================================================================

@_needs_archive
def test_neighbours_and_edge_between_agree_with_the_edge_list():
    inst = _load("a2-16")
    prof = assign_accessibility(inst, seed=1)
    g = build_compatibility_graph(inst, prof, max_group_size=2)
    for a, b in itertools.combinations(g.nodes, 2):
        edge = g.edge_between(a, b)
        assert (edge is not None) == (b in g.neighbours(a)) == (a in g.neighbours(b))


@_needs_archive
def test_isolated_requests_have_no_certified_group_of_any_order():
    inst = _load("a2-16")
    prof = assign_accessibility(inst, seed=1)
    g = build_compatibility_graph(inst, prof, max_group_size=3)
    for r in g.isolated():
        assert g.groups_containing(r) == ()
    assert set(g.isolated()) | {r for e in g.all_groups for r in e.request_ids} == set(g.nodes)


@_needs_archive
def test_a_hyperedge_is_not_taken_as_evidence_about_its_pairs():
    """Sub-group closure is NOT assumed. Every group is certified in its own
    right, so a triple in the graph never implies its pairs are feasible."""
    inst = _load("a3-18")
    prof = assign_accessibility(inst, seed=1)
    g = build_compatibility_graph(inst, prof, max_group_size=3)
    for h in g.hyperedges:
        for a, b in itertools.combinations(h.request_ids, 2):
            edge = g.edge_between(a, b)
            assert (edge is not None) == certify_group(inst, prof, [a, b], h.vehicle).certified


@_needs_archive
def test_the_graph_records_when_its_enumeration_was_truncated():
    inst = _load("a2-16")
    prof = assign_accessibility(inst, seed=1)
    full = build_compatibility_graph(inst, prof, max_group_size=2)
    assert not full.truncated
    cut = build_compatibility_graph(inst, prof, max_group_size=2, max_proposals=5)
    assert cut.truncated
    assert len(cut.edges) <= len(full.edges)


@_needs_archive
def test_the_graph_record_carries_the_assigned_labels_warning():
    inst = _load("a2-16")
    g = build_compatibility_graph(inst, assign_accessibility(inst, seed=1), max_group_size=2)
    record = g.to_record()
    assert "ASSIGNED, NOT OBSERVED" in record["accessibility"]["provenance"]
    assert record["accessibility"]["ASSIGNED_wheelchair_requests"]


def test_assign_accessibility_gives_an_exact_share_not_an_expected_one():
    inst = _toy()
    for share, expected in ((0.0, 0), (0.25, 1), (0.5, 2), (1.0, 4)):
        prof = assign_accessibility(inst, seed=7, wheelchair_share=share)
        assert len(prof.wheelchair_requests) == expected


def test_assign_accessibility_is_reproducible_and_validates_its_share():
    inst = _toy()
    assert assign_accessibility(inst, seed=3).wheelchair_requests == assign_accessibility(
        inst, seed=3
    ).wheelchair_requests
    with pytest.raises(ValueError):
        assign_accessibility(inst, seed=1, wheelchair_share=1.5)


def test_geometric_affinity_refuses_a_group_that_cannot_physically_fit():
    """It is only a heuristic and carries no authority -- but it should not spend
    the authority's time on groups whose floor demand exceeds the vehicle."""
    inst = _toy()
    prof = _toy_profile({1, 2})
    view = C._proposal_view(inst, prof, (1, 2), 0)
    assert geometric_affinity(view) == -math.inf
