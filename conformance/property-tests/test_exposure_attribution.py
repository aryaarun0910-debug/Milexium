"""Program F conformance: the exposure measurement and its capacity attribution.

Two claims are on trial here.

THE ATTRIBUTION IS WHAT IT SAYS IT IS. `attribute_capacity` returns minimal
blocking sets, and its definition is checked directly rather than trusted:
releasing a returned set must genuinely make the trip servable, and releasing any
PROPER SUBSET of it must not. A commitment is named `necessary` only when every
route to serving the rider ran through it, and that is verified a second way --
by releasing every other contender and confirming the rider is still stuck.

The honesty of the output is tested as hard as its correctness. A denial with
several sufficient causes must report several sets and name NO culprit; a search
that was truncated must not name one either, even when the sets it did find would
have supported one. Both directions are pinned, because a "cause" attributed to a
single rider who happened to book first is a fabrication with a name attached to
it.

THE BREAKDOWN DISCRIMINATES. The packet exists to tell "we served 3% fewer trips"
apart from "we served 3% fewer trips and every one of them needed a
wheelchair-accessible vehicle". So the suite contains BOTH: an instance where the
whole shortfall falls on wheelchair users, and an instance where it falls
entirely on ambulatory riders. A measurement that always blamed one cohort would
pass the first and fail the second, and only having both makes either meaningful.

Instances here are hand-built (small enough to verify by hand) or derived from the
acquired Cordeau academic set. Both support ALGORITHMIC claims only, and the
accessibility labels are ASSIGNED by the harness -- the published instances carry
no such attribute. Nothing here is evidence about any real operator's service.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone

import pytest

from packages.canonical import PolicyId, RequestId, TenantId, VehicleId, new_id
from packages.decide.capability import ortools_capability
from packages.decide.commingled import (
    CommingledFleet,
    CommingledInstance,
    InstanceProvenance,
    derive_commingled_instance,
    has_placement,
)
from packages.decide.darp_loader import find_benchmark_archive, load_zip_instance
from packages.decide.exposure import (
    AMBULATORY,
    WHEELCHAIR,
    attribute_capacity,
    measure_exposure,
)
from packages.decide.ir import (
    DecisionPolicy,
    DecisionProblem,
    DecisionVehicle,
    RideRequest,
)
from packages.decide.online import Arrival, first_fit, preserve_accessible_capacity, run_online

_CAP = ortools_capability()
_needs_cpsat = pytest.mark.skipif(not _CAP.available, reason=f"OR-Tools unavailable: {_CAP.detail}")
_ARCHIVE = find_benchmark_archive()
_needs_archive = pytest.mark.skipif(_ARCHIVE is None, reason="Cordeau DARP benchmark archive not acquired")

_BASE = datetime(2026, 7, 24, 9, 0, tzinfo=timezone.utc)


def _at(minute: int) -> datetime:
    return _BASE + timedelta(minutes=minute)


def _vehicle(amb: int, wc: int) -> DecisionVehicle:
    return DecisionVehicle(
        vehicle_id=new_id(VehicleId),
        capacity_ambulatory=amb,
        capacity_wheelchair=wc,
        shift_start=_BASE,
        shift_end=_BASE + timedelta(minutes=480),
    )


def _req(open_at: int, close_at: int, ride: int, *, wheelchair: bool = False, party: int = 1) -> RideRequest:
    return RideRequest(
        request_id=new_id(RequestId),
        pickup_window_start=_at(open_at),
        pickup_window_end=_at(close_at),
        dropoff_window_end=_at(close_at + ride + 30),
        needs_wheelchair=wheelchair,
        party_size=party,
        nominal_ride_time_minutes=float(ride),
        max_ride_time_minutes=float(ride) + 10.0,
        must_serve=False,
    )


def _problem(vehicles, requests) -> DecisionProblem:
    return DecisionProblem(
        tenant_id=new_id(TenantId),
        policy=DecisionPolicy(
            policy_id=new_id(PolicyId),
            name="exposure-test",
            time_granularity_minutes=5,
            unserved_penalty=100_000.0,
        ),
        vehicles=tuple(vehicles),
        requests=tuple(requests),
    )


def _stream(requests) -> tuple[Arrival, ...]:
    return tuple(
        Arrival(request=r, booked_at=_BASE - timedelta(minutes=100 - i))
        for i, r in enumerate(requests)
    )


def _instance(problem, fleet, requests, source="hand-built") -> CommingledInstance:
    """An instance whose arrival order is the list order, so a test can state the
    order it is reasoning about instead of inferring it."""
    return CommingledInstance(
        problem=problem,
        fleet=fleet,
        booked_at=tuple(
            (str(r.request_id), _BASE - timedelta(minutes=100 - i)) for i, r in enumerate(requests)
        ),
        provenance=InstanceProvenance(
            source=source,
            timing_from="hand-built in the conformance suite",
            accessibility_labels="hand-built",
            fleet_sizing="hand-built",
            booking_times="hand-built: arrival order is the list order",
            fleet_floor="hand-built",
            wheelchair_share=round(
                sum(1 for r in requests if r.needs_wheelchair) / len(requests), 4
            ),
            seed=0,
        ),
    )


# ==========================================================================
# Fixtures whose answers are known by hand.
# ==========================================================================

def _unique_bottleneck():
    """One accessible van with a three-seat floor. A two-seat party and a single
    rider fill it; a wheelchair user then needs two of the three seat-equivalents
    and cannot have them.

    Releasing the two-seat party leaves one seat used and two free -- enough.
    Releasing the single rider leaves two used and one free -- not enough. So the
    ONLY minimal blocking set is the two-seat party, and it is `necessary`. The
    single rider is a contender that turns out not to be a cause, which is what
    makes the test discriminating rather than a tautology.
    """
    van = _vehicle(amb=3, wc=1)
    party = _req(0, 0, 20, party=2)
    single = _req(0, 0, 20)
    chair = _req(0, 0, 20, wheelchair=True)
    problem = _problem([van], [party, single, chair])
    fleet = CommingledFleet.from_problem(problem, wheelchair_footprint=2)
    outcome = run_online(problem, fleet, _stream([party, single, chair]), first_fit, policy_name="ff")
    return problem, fleet, outcome, party, single, chair


def _two_disjoint_causes():
    """Two accessible vans, one seat each. Two ambulatory riders take one van
    apiece; a wheelchair user needs a whole floor and neither van has one free.

    Releasing EITHER rider would have served them. Two disjoint minimal blocking
    sets, so the denial has two sufficient causes and naming one would be false.
    """
    v1, v2 = _vehicle(amb=1, wc=1), _vehicle(amb=1, wc=1)
    a, b = _req(0, 0, 20), _req(0, 0, 20)
    chair = _req(0, 0, 20, wheelchair=True)
    problem = _problem([v1, v2], [a, b, chair])
    fleet = CommingledFleet.from_problem(problem, wheelchair_footprint=2)
    outcome = run_online(problem, fleet, _stream([a, b, chair]), first_fit, policy_name="ff")
    return problem, fleet, outcome, a, b, chair


def _wheelchair_bears_the_whole_shortfall():
    """One van with a two-seat floor. A flexible ambulatory rider books first and
    first-fit puts them at the front of their window; a wheelchair user with a
    rigid window then needs the whole floor and cannot have it.

    An offline scheduler seeing both would have started the ambulatory rider
    twenty minutes later and served both. The trip lost to not seeing the future
    is the wheelchair user's.
    """
    van = _vehicle(amb=2, wc=1)
    flexible = _req(0, 30, 20)
    chair = _req(0, 0, 20, wheelchair=True)
    problem = _problem([van], [flexible, chair])
    fleet = CommingledFleet.from_problem(problem, wheelchair_footprint=2)
    return _instance(problem, fleet, [flexible, chair], source="wheelchair-bears-it")


def _ambulatory_bears_the_whole_shortfall():
    """The mirror image, and the reason this file is trustworthy: the same
    mechanism with the cohorts swapped. A flexible wheelchair user books first and
    takes the floor at the front of their window; a rigid ambulatory rider is then
    turned away. The measurement must report a shortfall that is entirely
    AMBULATORY, or it is not measuring who bears the cost -- it is just asserting
    an answer.
    """
    van = _vehicle(amb=2, wc=1)
    flexible_chair = _req(0, 30, 20, wheelchair=True)
    rigid = _req(0, 0, 20)
    problem = _problem([van], [flexible_chair, rigid])
    fleet = CommingledFleet.from_problem(problem, wheelchair_footprint=2)
    return _instance(problem, fleet, [flexible_chair, rigid], source="ambulatory-bears-it")


# ==========================================================================
# The attribution: is it what it says it is?
# ==========================================================================

def test_a_returned_blocking_set_really_would_have_freed_the_capacity() -> None:
    """The definition, checked directly rather than trusted: releasing the set
    makes the trip servable, and releasing any PROPER SUBSET of it does not.
    Minimality is the difference between an attribution and a list of everyone
    who happened to be on the vehicle."""
    problem, fleet, outcome, *_ = _unique_bottleneck()
    rid = outcome.declined_ids[0]
    request = next(r for r in problem.requests if str(r.request_id) == rid)
    att = attribute_capacity(problem, fleet, outcome, rid)
    prior = outcome.accepted_before(att.sequence)
    assert att.blocking_sets, "the fixture must produce at least one blocking set"

    for blocking in att.blocking_sets:
        kept = [a for a in prior if a.request_id not in set(blocking)]
        assert has_placement(problem, fleet, kept, request), f"releasing {blocking} did not free capacity"
        for size in range(len(blocking)):
            for sub in itertools.combinations(blocking, size):
                partial = [a for a in prior if a.request_id not in set(sub)]
                assert not has_placement(problem, fleet, partial, request), (
                    f"the proper subset {sub} of {blocking} already sufficed, so {blocking} is not minimal"
                )


def test_the_only_route_to_serving_the_rider_is_named_and_the_bystander_is_not() -> None:
    """The single case where naming an individual trip is honest, plus the
    negative half that makes it a real test: the other rider on the vehicle is a
    contender, was examined, and is NOT named."""
    problem, fleet, outcome, party, single, chair = _unique_bottleneck()
    att = attribute_capacity(problem, fleet, outcome, str(chair.request_id))

    assert att.enumeration_complete is True
    assert att.contenders_examined == 2
    assert att.blocking_sets == ((str(party.request_id),),)
    assert att.necessary_commitments == (str(party.request_id),)
    assert str(single.request_id) not in att.necessary_commitments
    assert dict(att.participation) == {str(party.request_id): 1.0}


def test_necessity_is_verified_a_second_way_by_releasing_everyone_else() -> None:
    """An independent check of the same claim, computed differently.

    If a commitment is in every minimal blocking set then releasing every OTHER
    contender must still leave the rider stuck -- otherwise the released group
    would itself have been a blocking set not containing it. Recomputed here from
    placement feasibility rather than from the set algebra the module used.
    """
    problem, fleet, outcome, *_ = _unique_bottleneck()
    rid = outcome.declined_ids[0]
    request = next(r for r in problem.requests if str(r.request_id) == rid)
    att = attribute_capacity(problem, fleet, outcome, rid)
    prior = outcome.accepted_before(att.sequence)
    assert att.necessary_commitments, "the fixture must name at least one necessary commitment"

    for necessary in att.necessary_commitments:
        only_this_one = [a for a in prior if a.request_id == necessary]
        assert not has_placement(problem, fleet, only_this_one, request), (
            f"{necessary} was named necessary, but the rider is servable with it alone in place"
        )


def test_a_denial_with_several_sufficient_causes_names_none_of_them() -> None:
    """Two disjoint minimal blocking sets. Releasing either would have served the
    rider, so no single commitment caused the denial, and the output must say so
    rather than blaming whoever booked first."""
    problem, fleet, outcome, a, b, chair = _two_disjoint_causes()
    att = attribute_capacity(problem, fleet, outcome, str(chair.request_id))

    assert att.enumeration_complete is True
    assert len(att.blocking_sets) == 2
    assert {frozenset(s) for s in att.blocking_sets} == {
        frozenset({str(a.request_id)}), frozenset({str(b.request_id)})
    }
    assert att.necessary_commitments == ()
    assert dict(att.participation) == {str(a.request_id): 0.5, str(b.request_id): 0.5}
    assert "sufficient" not in att.detail  # the detail states the count, it does not editorialise
    assert "2 minimal blocking set(s)" in att.detail


def test_a_truncated_search_refuses_to_name_a_necessary_commitment() -> None:
    """The same instance as the named-culprit test, searched with a budget too
    small to be exhaustive. The blocking set is still found and still reported --
    but "every route ran through it" is a claim about routes not searched, so it
    is withheld. A partial search that named a culprit anyway would be the most
    damaging bug in this module."""
    problem, fleet, outcome, party, _single, chair = _unique_bottleneck()
    truncated = attribute_capacity(problem, fleet, outcome, str(chair.request_id), max_set_size=1)

    assert truncated.enumeration_complete is False
    assert truncated.blocking_sets == ((str(party.request_id),),)
    assert truncated.necessary_commitments == ()
    assert "BOUNDED" in truncated.detail

    exhaustive = attribute_capacity(problem, fleet, outcome, str(chair.request_id), max_set_size=3)
    assert exhaustive.enumeration_complete is True
    assert exhaustive.necessary_commitments == (str(party.request_id),)


def test_a_structurally_impossible_trip_is_not_blamed_on_another_rider() -> None:
    """A wheelchair user against a fleet with no wheelchair position anywhere.
    They could not have been served on an EMPTY fleet, so the denial is a gap in
    the service and attributing it to a general-public rider would be false --
    and would be the single most misleading output this module could produce."""
    van = _vehicle(amb=3, wc=0)
    rider = _req(0, 30, 20)
    chair = _req(0, 30, 20, wheelchair=True)
    problem = _problem([van], [rider, chair])
    fleet = CommingledFleet.from_problem(problem, wheelchair_footprint=2)
    outcome = run_online(problem, fleet, _stream([rider, chair]), first_fit, policy_name="ff")

    att = attribute_capacity(problem, fleet, outcome, str(chair.request_id))
    assert att.servable_in_isolation is False
    assert att.blocking_sets == ()
    assert att.necessary_commitments == ()
    assert att.has_attribution is False
    assert "EMPTY fleet" in att.detail and "structural gap" in att.detail


def test_attribution_is_refused_for_a_request_that_was_served() -> None:
    problem, fleet, outcome, party, _single, _chair = _unique_bottleneck()
    with pytest.raises(ValueError, match="was accepted"):
        attribute_capacity(problem, fleet, outcome, str(party.request_id))


def test_no_attribution_ever_names_a_commitment_made_after_the_denial() -> None:
    """A commitment made later cannot have consumed capacity for an earlier
    decision. Enforced by the harness's arrival ordering, checked here because a
    version of the attribution that looked at the whole accepted set would be
    quietly, plausibly wrong."""
    problem, fleet, outcome, *_ = _unique_bottleneck()
    for rid in outcome.declined_ids:
        att = attribute_capacity(problem, fleet, outcome, rid)
        later = {c.request_id for c in outcome.commitments if c.sequence > att.sequence}
        named = {i for s in att.blocking_sets for i in s}
        assert not (named & later)


@_needs_archive
def test_blocking_sets_hold_their_definition_across_a_derived_corpus() -> None:
    """The property, at scale, on instances derived from published academic
    timing data. Also a non-vacuity guard: the corpus must actually produce
    attributions, or the property above is checked against an empty set."""
    attributed = 0
    for name in ("a3-24", "a3-30", "a3-36"):
        darp = load_zip_instance(_ARCHIVE, name)
        for seed in (1, 3):
            inst = derive_commingled_instance(darp, seed=seed, vehicle_capacity=2)
            outcome = run_online(
                inst.problem, inst.fleet, _to_arrivals(inst), first_fit, policy_name="first-fit"
            )
            for rid in outcome.declined_ids:
                att = attribute_capacity(inst.problem, inst.fleet, outcome, rid)
                assert att.necessary_commitments == () or att.enumeration_complete
                if not att.servable_in_isolation:
                    assert att.blocking_sets == ()
                    continue
                request = next(r for r in inst.problem.requests if str(r.request_id) == rid)
                prior = outcome.accepted_before(att.sequence)
                for blocking in att.blocking_sets:
                    kept = [a for a in prior if a.request_id not in set(blocking)]
                    assert has_placement(inst.problem, inst.fleet, kept, request)
                    attributed += 1
    assert attributed >= 3, (
        f"only {attributed} blocking sets across the derived corpus; the property is barely exercised"
    )


def _to_arrivals(inst: CommingledInstance):
    from packages.decide.online import arrivals_from

    return arrivals_from(inst.problem, inst.booked_at)


# ==========================================================================
# The breakdown: does it tell the two sentences apart?
# ==========================================================================

@_needs_cpsat
def test_a_shortfall_borne_entirely_by_wheelchair_users_is_reported_as_such() -> None:
    """The sentence the packet exists for."""
    report = measure_exposure(
        _wheelchair_bears_the_whole_shortfall(), first_fit, policy_name="first-fit"
    )
    assert report.offline_proven_optimal is True
    assert report.shortfall == 1
    wc = next(c for c in report.cohorts if c.cohort == WHEELCHAIR)
    amb = next(c for c in report.cohorts if c.cohort == AMBULATORY)
    assert wc.shortfall == 1 and amb.shortfall == 0
    assert wc.share_of_shortfall == 1.0
    assert report.concentration == 2.0  # 100% of the shortfall against 50% of demand
    assert "EVERY ONE of them needed a wheelchair-accessible vehicle" in report.headline()


@_needs_cpsat
def test_the_same_measurement_reports_an_ambulatory_shortfall_when_that_is_the_truth() -> None:
    """The half that makes the half above worth anything. Same mechanism, cohorts
    swapped: a measurement hard-wired to blame wheelchair users would pass the
    previous test and fail this one."""
    report = measure_exposure(
        _ambulatory_bears_the_whole_shortfall(), first_fit, policy_name="first-fit"
    )
    assert report.shortfall == 1
    wc = next(c for c in report.cohorts if c.cohort == WHEELCHAIR)
    amb = next(c for c in report.cohorts if c.cohort == AMBULATORY)
    assert wc.shortfall == 0 and amb.shortfall == 1
    assert report.concentration == 0.0
    assert "EVERY ONE" not in report.headline()
    assert "0 of them needed a wheelchair-accessible vehicle" in report.headline()


@_needs_cpsat
def test_cohort_shortfalls_sum_to_the_total_and_shares_sum_to_one() -> None:
    report = measure_exposure(
        _wheelchair_bears_the_whole_shortfall(), first_fit, policy_name="first-fit"
    )
    assert sum(c.shortfall for c in report.cohorts) == report.shortfall
    assert sum(c.demand for c in report.cohorts) == report.requests
    assert abs(sum(c.share_of_demand for c in report.cohorts) - 1.0) < 1e-9
    assert abs(sum(c.share_of_shortfall for c in report.cohorts) - 1.0) < 1e-9


@_needs_cpsat
def test_a_run_that_matched_the_optimum_reports_no_concentration_rather_than_zero() -> None:
    """With no shortfall there is nothing to distribute. Reporting a
    concentration of 0 or 1 would invent a finding out of an empty numerator."""
    van = _vehicle(amb=3, wc=1)
    reqs = [_req(0, 60, 20), _req(120, 180, 20, wheelchair=True)]
    problem = _problem([van], reqs)
    fleet = CommingledFleet.from_problem(problem, wheelchair_footprint=2)
    report = measure_exposure(_instance(problem, fleet, reqs), first_fit, policy_name="first-fit")

    assert report.shortfall == 0
    assert report.concentration is None
    assert all(c.share_of_shortfall is None for c in report.cohorts)
    assert "No cost of foresight to distribute" in report.headline()


@_needs_cpsat
def test_the_report_never_credits_the_online_run_with_beating_the_optimum() -> None:
    """Across every hand-built fixture: the offline optimum sees everything and is
    proven; a negative shortfall would mean one of the two procedures is wrong."""
    for instance in (
        _wheelchair_bears_the_whole_shortfall(),
        _ambulatory_bears_the_whole_shortfall(),
    ):
        for policy, name in ((first_fit, "first-fit"), (preserve_accessible_capacity, "preserve")):
            report = measure_exposure(instance, policy, policy_name=name)
            assert report.shortfall >= 0
            assert report.served_online <= report.served_offline
            assert report.objective_online >= report.objective_offline - 1e-6


@_needs_cpsat
def test_the_report_carries_whether_the_floor_bound_at_all() -> None:
    """A reader must be able to tell a measured zero from a structurally
    impossible one. On a fleet with dedicated wheelchair space there is no
    commingling to measure and the report says so."""
    van = _vehicle(amb=2, wc=1)
    reqs = [_req(0, 30, 20), _req(0, 0, 20, wheelchair=True)]
    problem = _problem([van], reqs)
    dedicated = CommingledFleet(floor_units=((str(van.vehicle_id), 2),), wheelchair_footprint=0)
    report = measure_exposure(_instance(problem, dedicated, reqs), first_fit, policy_name="first-fit")
    assert report.floor_binds is False
    assert report.shortfall == 0

    shared = CommingledFleet.from_problem(problem, wheelchair_footprint=2)
    contended = measure_exposure(_instance(problem, shared, reqs), first_fit, policy_name="first-fit")
    assert contended.floor_binds is True
    assert contended.shortfall == 1


@_needs_cpsat
def test_the_pool_only_relaxation_cross_check_runs_and_bounds_the_optimum() -> None:
    """`packages.decide.cpsat`, unmodified, solves the same instance without the
    floor. A relaxation cannot serve fewer trips; `measure_exposure` raises if it
    does, so a bug in either CP-SAT model surfaces here rather than as a plausible
    exposure number."""
    report = measure_exposure(
        _wheelchair_bears_the_whole_shortfall(), first_fit, policy_name="first-fit"
    )
    assert report.pool_only_proven is True
    assert report.pool_only_served >= report.served_offline
    assert report.pool_only_served == 2  # without the shared floor both trips fit


@_needs_cpsat
def test_window_deferral_is_reported_per_cohort_but_never_attributed() -> None:
    """Degradation is described, not traced. A trip pushed to the far end of its
    window is a degraded trip and a served-count alone hides it; the honest limit
    is that only outright denials are attributed to the capacity they needed."""
    report = measure_exposure(
        _wheelchair_bears_the_whole_shortfall(), first_fit, policy_name="first-fit"
    )
    amb = next(c for c in report.cohorts if c.cohort == AMBULATORY)
    assert amb.mean_window_deferral_online_minutes == 0.0     # first-fit took the front of the window
    assert amb.mean_window_deferral_offline_minutes == 20.0   # the optimum waited, and served both
    assert all(not a.needs_wheelchair or a.servable_in_isolation for a in report.attributions)


@_needs_cpsat
def test_the_serialisable_record_carries_the_qualifiers_not_just_the_number() -> None:
    """A number that escapes its caveats is worse than no number. The record must
    carry whether the offline side was proven, whether the floor bound, and the
    attribution detail strings."""
    report = measure_exposure(
        _wheelchair_bears_the_whole_shortfall(), first_fit, policy_name="first-fit"
    )
    record = report.to_record()
    assert record["offline_proven_optimal"] is True
    assert record["floor_constraint_binds"] is True
    assert record["shortfall_pct_of_demand"] == 50.0
    assert record["headline"] == report.headline()
    assert all("enumeration_complete" in a for a in record["attributions"])


# ==========================================================================
# Derived instances: the measurement end to end.
# ==========================================================================

@_needs_cpsat
@_needs_archive
def test_placement_alone_recovers_wheelchair_trips_without_declining_anyone() -> None:
    """THE FRAMING RESULT, and the reason this measurement is about releasing
    capacity rather than rationing it.

    Both policies serve every rider they possibly can -- the harness aborts
    otherwise. The only difference is that one of them keeps ambulatory riders off
    the accessible vehicles when there is anywhere else to put them. On a corpus
    of derived instances that must recover wheelchair trips, not trade them away.
    """
    darp = load_zip_instance(_ARCHIVE, "a3-36")
    recovered = 0
    for seed in (1, 2, 3):
        instance = derive_commingled_instance(darp, seed=seed, vehicle_capacity=2)
        baseline = measure_exposure(
            instance, first_fit, policy_name="first-fit",
            max_deterministic_time=30.0, include_pool_only_check=False,
        )
        preserving = measure_exposure(
            instance, preserve_accessible_capacity, policy_name="preserve-accessible-capacity",
            max_deterministic_time=30.0, include_pool_only_check=False,
        )
        assert preserving.served_online >= baseline.served_online, (
            "the placement rule must never cost a trip overall"
        )
        wc_base = next(c for c in baseline.cohorts if c.cohort == WHEELCHAIR)
        wc_pres = next(c for c in preserving.cohorts if c.cohort == WHEELCHAIR)
        assert wc_pres.served_online >= wc_base.served_online
        recovered += wc_pres.served_online - wc_base.served_online
    assert recovered >= 1, (
        f"the placement rule recovered {recovered} wheelchair trips across the corpus; with none, "
        f"this test would pass for a policy identical to the baseline"
    )


@_needs_cpsat
@_needs_archive
def test_a_derived_instance_produces_a_shortfall_borne_by_the_accessible_cohort() -> None:
    """End to end on published academic timing data. The claim being pinned is
    that the measurement produces a NON-ZERO, cohort-concentrated result on an
    instance nobody in this repository designed to produce one -- not that any
    real service behaves this way."""
    instance = derive_commingled_instance(
        load_zip_instance(_ARCHIVE, "a3-36"), seed=1, vehicle_capacity=2
    )
    report = measure_exposure(
        instance, first_fit, policy_name="first-fit", max_deterministic_time=30.0
    )
    assert report.offline_proven_optimal is True
    assert report.floor_binds is True
    assert report.shortfall > 0
    assert report.concentration is not None and report.concentration > 1.0
    assert report.attributions, "every declined trip should carry an attribution"
