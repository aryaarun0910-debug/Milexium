"""Program F conformance: online commitment in a commingled service.

The claims this file has to earn are the ones that make the exposure number mean
what it says. If any of them is false, the measurement is an offline re-plan
wearing an online harness's name and every figure it produces is wrong:

- NO LOOKAHEAD, in its testable form: two arrival streams sharing a prefix
  produce identical commitments on that prefix. A scheduler that peeked at the
  tail could not satisfy this.
- IRREVOCABILITY: every assignment in the finished plan is byte-identical to the
  placement recorded at the instant of commitment. Nothing is re-optimised.
- THE HARNESS WILL NOT RUN A RATIONING POLICY. A policy that declines a servable
  rider aborts the run.
- THE FLOOR CONSTRAINT ACTUALLY BINDS. `packages.decide.commingled` exists
  because the v0.1 IR's two capacity pools are independent, under which
  commingling is free and every assertion here would be vacuously true. So the
  suite pins a concrete case where the floor rejects a plan the pools accept, and
  the property tests REFUSE to pass on a corpus where the floor never bound --
  the exact shape of the "vacuous at K=1 where every instance was K=1" failure
  this repository has shipped before.
- THE ONLINE RUN NEVER BEATS THE OFFLINE OPTIMUM, which is a cross-check between
  two entirely separate procedures and would catch either one being wrong.

Instances are hand-built or derived from the acquired Cordeau academic benchmark
set. Both support ALGORITHMIC claims only, and the accessibility labels on the
derived ones are ASSIGNED by the harness because the source files carry no such
attribute. Nothing here is evidence about any real operator's service.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from packages.canonical import PolicyId, RequestId, TenantId, VehicleId, new_id
from packages.canonical.vocab import ScheduleRunStatus
from packages.decide.capability import ortools_capability
from packages.decide.commingled import (
    AcceptedRide,
    CommingledFleet,
    DenialPenaltyTooWeak,
    Placement,
    assert_denial_dominates,
    check_commingled,
    check_floor_feasibility,
    derive_commingled_instance,
    feasible_placements,
    has_placement,
    pool_only_relaxation,
    solve_commingled_offline,
)
from packages.decide.darp_loader import find_benchmark_archive, load_zip_instance
from packages.decide.feasibility import check_feasibility
from packages.decide.ir import (
    Assignment,
    DecisionPolicy,
    DecisionProblem,
    DecisionSolution,
    DecisionVehicle,
    RideRequest,
)
from packages.decide.online import (
    Arrival,
    InvalidPlacement,
    RationingRefused,
    arrivals_from,
    first_fit,
    preserve_accessible_capacity,
    run_online,
)

_CAP = ortools_capability()
_needs_cpsat = pytest.mark.skipif(not _CAP.available, reason=f"OR-Tools unavailable: {_CAP.detail}")
_ARCHIVE = find_benchmark_archive()
_needs_archive = pytest.mark.skipif(_ARCHIVE is None, reason="Cordeau DARP benchmark archive not acquired")

_BASE = datetime(2026, 7, 24, 9, 0, tzinfo=timezone.utc)


def _at(minute: int) -> datetime:
    return _BASE + timedelta(minutes=minute)


def _policy(**kw) -> DecisionPolicy:
    kw.setdefault("unserved_penalty", 100_000.0)
    kw.setdefault("time_granularity_minutes", 5)
    return DecisionPolicy(policy_id=new_id(PolicyId), name="commingled-test", **kw)


def _vehicle(amb: int, wc: int, shift_minutes: int = 480) -> DecisionVehicle:
    return DecisionVehicle(
        vehicle_id=new_id(VehicleId),
        capacity_ambulatory=amb,
        capacity_wheelchair=wc,
        shift_start=_BASE,
        shift_end=_BASE + timedelta(minutes=shift_minutes),
    )


def _req(
    *,
    open_at: int,
    close_at: int,
    ride: int,
    wheelchair: bool = False,
    party: int = 1,
    dropoff_slack: int = 30,
) -> RideRequest:
    return RideRequest(
        request_id=new_id(RequestId),
        pickup_window_start=_at(open_at),
        pickup_window_end=_at(close_at),
        dropoff_window_end=_at(close_at + ride + dropoff_slack),
        needs_wheelchair=wheelchair,
        party_size=party,
        nominal_ride_time_minutes=float(ride),
        max_ride_time_minutes=float(ride) + 10.0,
        must_serve=False,
    )


def _problem(vehicles, requests, **policy_kw) -> DecisionProblem:
    return DecisionProblem(
        tenant_id=new_id(TenantId),
        policy=_policy(**policy_kw),
        vehicles=tuple(vehicles),
        requests=tuple(requests),
    )


def _stream(requests) -> tuple[Arrival, ...]:
    """Arrivals in the order given, one minute apart. Keeps the arrival ORDER --
    the thing the online scheduler cannot control -- explicit in each test."""
    return tuple(
        Arrival(request=r, booked_at=_BASE - timedelta(minutes=100 - i))
        for i, r in enumerate(requests)
    )


# ==========================================================================
# The floor: the constraint without which this whole package is vacuous.
# ==========================================================================

def test_the_two_ir_capacity_pools_cannot_express_commingling_at_all() -> None:
    """The premise of `packages.decide.commingled`, pinned as a fact.

    Three ambulatory riders and one wheelchair rider on a van with three seats and
    one wheelchair position. The IR's independent pools accept it: the ambulatory
    pool sees 3 of 3, the wheelchair pool sees 1 of 1, neither sees the other. The
    van physically cannot do it -- the station is made by folding the bench.

    If this test ever fails because `check_feasibility` started rejecting the
    plan, then the IR grew a shared-capacity model and this package's floor became
    redundant. That is a good outcome and should be handled, not patched around.
    """
    veh = _vehicle(amb=3, wc=1)
    riders = [_req(open_at=0, close_at=0, ride=20) for _ in range(3)]
    chair = _req(open_at=0, close_at=0, ride=20, wheelchair=True)
    problem = _problem([veh], riders + [chair])
    solution = DecisionSolution(
        status=ScheduleRunStatus.FEASIBLE,
        assignments=tuple(
            Assignment(
                request_id=r.request_id,
                vehicle_id=veh.vehicle_id,
                pickup_time=_at(0),
                dropoff_time=_at(20),
            )
            for r in riders + [chair]
        ),
        seed=0,
        solver_name="test",
        solver_version="0",
    )
    fleet = CommingledFleet.from_problem(problem, wheelchair_footprint=2)

    assert check_feasibility(problem, solution) == [], "the IR's pools accept it"
    floor = check_floor_feasibility(problem, fleet, solution)
    assert floor, "the shared floor must reject 3 seats + a 2-seat wheelchair station on a 3-seat van"
    assert "floor load" in floor[0].detail
    assert check_commingled(problem, fleet, solution), "the combined gate must reject it too"


def test_floor_checker_accepts_a_load_that_fits() -> None:
    """The floor rejects, but not everything -- a checker that rejected all plans
    would pass the test above while proving nothing."""
    veh = _vehicle(amb=3, wc=1)
    rider = _req(open_at=0, close_at=0, ride=20)
    chair = _req(open_at=0, close_at=0, ride=20, wheelchair=True)
    problem = _problem([veh], [rider, chair])
    fleet = CommingledFleet.from_problem(problem, wheelchair_footprint=2)
    solution = DecisionSolution(
        status=ScheduleRunStatus.FEASIBLE,
        assignments=(
            Assignment(request_id=rider.request_id, vehicle_id=veh.vehicle_id, pickup_time=_at(0), dropoff_time=_at(20)),
            Assignment(request_id=chair.request_id, vehicle_id=veh.vehicle_id, pickup_time=_at(0), dropoff_time=_at(20)),
        ),
        seed=0,
        solver_name="test",
        solver_version="0",
    )
    assert check_floor_feasibility(problem, fleet, solution) == []


def test_floor_frees_at_the_instant_the_previous_rider_leaves() -> None:
    """Boundary convention, pinned: a drop-off releases the floor at the same
    instant the next pickup takes it, matching the IR checker's own sweep. An
    off-by-one here would invent denials that never happened."""
    veh = _vehicle(amb=1, wc=1)
    a = _req(open_at=0, close_at=0, ride=20)
    b = _req(open_at=20, close_at=20, ride=20)
    problem = _problem([veh], [a, b])
    fleet = CommingledFleet.from_problem(problem, wheelchair_footprint=2)
    solution = DecisionSolution(
        status=ScheduleRunStatus.FEASIBLE,
        assignments=(
            Assignment(request_id=a.request_id, vehicle_id=veh.vehicle_id, pickup_time=_at(0), dropoff_time=_at(20)),
            Assignment(request_id=b.request_id, vehicle_id=veh.vehicle_id, pickup_time=_at(20), dropoff_time=_at(40)),
        ),
        seed=0,
        solver_name="test",
        solver_version="0",
    )
    assert check_floor_feasibility(problem, fleet, solution) == []


def test_a_zero_footprint_fleet_reports_no_commingling_effect_at_all() -> None:
    """The floor is a claim about a VEHICLE, and the honest consequence of the
    other claim is pinned here: a fleet whose wheelchair stations sit in dedicated
    floor space (footprint 0 against the seats) has nothing to trade, and this
    package correctly measures nothing. `binds_anywhere` is what a caller checks
    before drawing any conclusion."""
    veh = _vehicle(amb=3, wc=1)
    problem = _problem([veh], [_req(open_at=0, close_at=0, ride=20)])
    dedicated = CommingledFleet(floor_units=((str(veh.vehicle_id), 3),), wheelchair_footprint=0)
    assert dedicated.binds_anywhere(problem) is False
    shared = CommingledFleet.from_problem(problem, wheelchair_footprint=2)
    assert shared.binds_anywhere(problem) is True


def test_default_floor_widens_for_a_wheelchair_only_van() -> None:
    """A van with no ambulatory seats and one wheelchair position would otherwise
    be given a floor of zero and could carry nobody -- a modelling default turning
    into a fake denial."""
    veh = _vehicle(amb=0, wc=1)
    problem = _problem([veh], [_req(open_at=0, close_at=0, ride=20, wheelchair=True)])
    fleet = CommingledFleet.from_problem(problem, wheelchair_footprint=2)
    assert fleet.units(str(veh.vehicle_id)) == 2
    assert has_placement(problem, fleet, (), problem.requests[0])


# ==========================================================================
# Placement enumeration.
# ==========================================================================

def test_has_placement_agrees_with_feasible_placements() -> None:
    """The attribution calls `has_placement` thousands of times because building
    every placement would be too slow. If the two ever disagreed, every blocking
    set would be computed against a different feasibility rule than the run that
    produced the denial."""
    veh_a, veh_b = _vehicle(amb=2, wc=1), _vehicle(amb=2, wc=0)
    reqs = [
        _req(open_at=0, close_at=30, ride=20),
        _req(open_at=10, close_at=25, ride=15, wheelchair=True),
        _req(open_at=0, close_at=5, ride=40),
        _req(open_at=200, close_at=240, ride=20, wheelchair=True),
    ]
    problem = _problem([veh_a, veh_b], reqs)
    fleet = CommingledFleet.from_problem(problem, wheelchair_footprint=2)
    accepted: list[AcceptedRide] = []
    for r in reqs:
        options = feasible_placements(problem, fleet, tuple(accepted), r)
        assert has_placement(problem, fleet, tuple(accepted), r) is bool(options)
        if options:
            accepted.append(
                AcceptedRide(
                    request_id=str(r.request_id),
                    placement=options[0],
                    needs_wheelchair=r.needs_wheelchair,
                    party_size=r.party_size,
                )
            )
    assert accepted, "a corpus where nothing was ever placeable would prove nothing"


def test_placements_respect_both_gates_not_just_one() -> None:
    """Every placement offered must satisfy the IR pools AND the floor. Pinned by
    committing to each one in turn and asking both checkers."""
    veh = _vehicle(amb=3, wc=1)
    seated = _req(open_at=0, close_at=0, ride=30, party=2)
    chair = _req(open_at=0, close_at=30, ride=20, wheelchair=True)
    problem = _problem([veh], [seated, chair])
    fleet = CommingledFleet.from_problem(problem, wheelchair_footprint=2)
    prior = (
        AcceptedRide(
            request_id=str(seated.request_id),
            placement=Placement(str(veh.vehicle_id), _at(0), _at(30)),
            needs_wheelchair=False,
            party_size=2,
        ),
    )
    options = feasible_placements(problem, fleet, prior, chair)
    assert options, "the wheelchair rider must still be servable after the 30-minute window"
    # Two seats of a three-seat floor are taken until minute 30, and the station
    # needs two, so every remaining option must start at or after minute 30.
    assert all(p.pickup_time >= _at(30) for p in options)


# ==========================================================================
# The three structural properties of the online harness.
# ==========================================================================

def _contended_problem():
    """One accessible van, four riders whose windows overlap. Small enough to
    reason about by hand, tight enough that the floor genuinely binds."""
    veh = _vehicle(amb=2, wc=1)
    reqs = [
        _req(open_at=0, close_at=10, ride=25),
        _req(open_at=0, close_at=10, ride=25),
        _req(open_at=5, close_at=15, ride=20, wheelchair=True),
        _req(open_at=5, close_at=20, ride=20),
    ]
    problem = _problem([veh], reqs)
    return problem, CommingledFleet.from_problem(problem, wheelchair_footprint=2), reqs


def test_no_lookahead_shows_up_as_prefix_determinism() -> None:
    """THE property that says "cannot see the future".

    The same first three arrivals are followed by two completely different tails.
    A scheduler with any visibility of what is coming could commit differently on
    the shared prefix; this one cannot, so the prefix commitments are identical.
    """
    _p, _f, reqs = _contended_problem()
    tail_a = _req(open_at=60, close_at=90, ride=20, wheelchair=True)
    tail_b = _req(open_at=0, close_at=5, ride=30)
    prefix = reqs[:3]
    # ONE problem holding every request, so the two runs differ ONLY in which
    # arrivals reach the scheduler and in what order -- never in the fleet.
    problem = _problem([_vehicle(amb=2, wc=1)], prefix + [tail_a, tail_b])
    fleet = CommingledFleet.from_problem(problem, wheelchair_footprint=2)

    with_a = run_online(problem, fleet, _stream(prefix + [tail_a]), first_fit, policy_name="ff")
    with_b = run_online(problem, fleet, _stream(prefix + [tail_b]), first_fit, policy_name="ff")
    prefix_only = run_online(problem, fleet, _stream(prefix), first_fit, policy_name="ff")

    assert with_a.commitments[:3] == with_b.commitments[:3] == prefix_only.commitments
    # Non-vacuity: the two tails must actually have been decided differently, or
    # this would pass on two identical runs.
    assert with_a.commitments[3] != with_b.commitments[3]


def test_every_assignment_equals_the_placement_committed_to_at_the_time() -> None:
    """IRREVOCABILITY. Nothing was re-optimised on the way out; if it had been,
    the run would be an offline re-plan and the measured gap would be zero for the
    wrong reason."""
    problem, fleet, _reqs = _contended_problem()
    outcome = run_online(problem, fleet, _stream(problem.requests), first_fit, policy_name="ff")
    by_id = {str(a.request_id): a for a in outcome.solution.assignments}
    assert by_id, "a run that committed to nothing would make this vacuous"
    for ride in outcome.accepted:
        a = by_id[ride.request_id]
        assert str(a.vehicle_id) == ride.placement.vehicle_id
        assert a.pickup_time == ride.placement.pickup_time
        assert a.dropoff_time == ride.placement.dropoff_time
        assert outcome.commitment_for(ride.request_id).placement == ride.placement


def test_a_policy_that_declines_a_servable_rider_aborts_the_run() -> None:
    """THE ANTI-RATIONING GUARD. No result is produced at all, so no number from
    this harness can be quoted in support of declining riders."""
    # A deliberately UNcontended instance: an empty accessible van and one
    # wheelchair rider, so the declined rider provably had somewhere to go and
    # the guard cannot be passing for the wrong reason.
    van = _vehicle(amb=2, wc=1)
    chair = _req(open_at=0, close_at=30, ride=20, wheelchair=True)
    problem = _problem([van], [chair])
    fleet = CommingledFleet.from_problem(problem, wheelchair_footprint=2)
    assert has_placement(problem, fleet, (), chair)

    def refuse_wheelchair_riders(view):
        if view.request.needs_wheelchair:
            return None
        return view.options[0] if view.options else None

    with pytest.raises(RationingRefused) as exc:
        run_online(problem, fleet, _stream([chair]), refuse_wheelchair_riders, policy_name="rationing")
    assert "feasible placements existed" in str(exc.value)
    # And the same policy on a request it does not discriminate against runs fine,
    # so the guard fires on the DECISION, not on the policy's identity.
    rider = _req(open_at=0, close_at=30, ride=20)
    ok_problem = _problem([van], [rider])
    ok_fleet = CommingledFleet.from_problem(ok_problem, wheelchair_footprint=2)
    assert run_online(ok_problem, ok_fleet, _stream([rider]), refuse_wheelchair_riders, policy_name="rationing").accepted


def test_a_policy_cannot_invent_a_placement_the_harness_did_not_offer() -> None:
    """Both capacity gates live in the harness's enumeration. A policy free to
    return its own placement would bypass them."""
    problem, fleet, _reqs = _contended_problem()
    ghost = Placement(str(problem.vehicles[0].vehicle_id), _at(0), _at(400))

    with pytest.raises(InvalidPlacement):
        run_online(problem, fleet, _stream(problem.requests), lambda v: ghost, policy_name="ghost")


def test_every_decline_in_a_real_run_had_no_feasible_placement() -> None:
    """The guard above raises on a policy that rations. This checks the other
    direction on a real run: each recorded decline is re-derived from the prefix
    of commitments that existed at that moment, and must genuinely have had
    nowhere to go."""
    problem, fleet, _reqs = _contended_problem()
    outcome = run_online(problem, fleet, _stream(problem.requests), first_fit, policy_name="ff")
    declined = outcome.declined_ids
    assert declined, "an instance where nothing was declined cannot test this"
    for rid in declined:
        seq = outcome.commitment_for(rid).sequence
        request = next(r for r in problem.requests if str(r.request_id) == rid)
        assert not has_placement(problem, fleet, outcome.accepted_before(seq), request)


def test_online_plans_pass_both_independent_checkers() -> None:
    problem, fleet, _reqs = _contended_problem()
    for policy, name in ((first_fit, "first-fit"), (preserve_accessible_capacity, "preserve")):
        outcome = run_online(problem, fleet, _stream(problem.requests), policy, policy_name=name)
        assert check_feasibility(problem, outcome.solution) == []
        assert check_floor_feasibility(problem, fleet, outcome.solution) == []


def test_an_online_run_never_claims_optimality() -> None:
    """A sequential run proves nothing about what was reachable. FEASIBLE, no
    bound, no gap -- the blueprint-15 failure mode, held here too."""
    problem, fleet, _reqs = _contended_problem()
    outcome = run_online(problem, fleet, _stream(problem.requests), first_fit, policy_name="ff")
    assert outcome.solution.status is ScheduleRunStatus.FEASIBLE
    assert outcome.solution.bound is None and outcome.solution.gap is None
    assert outcome.solution.proven_optimal is False


def test_both_shipped_policies_serve_every_rider_they_possibly_can() -> None:
    """The framing invariant, tested on both policies over many seeded instances.
    They differ only in WHERE a rider is placed. Neither can withhold a trip --
    the harness would abort if it tried."""
    archive_free = _small_random_corpus()
    checked = 0
    for problem, fleet, reqs in archive_free:
        for policy, name in ((first_fit, "first-fit"), (preserve_accessible_capacity, "preserve")):
            outcome = run_online(problem, fleet, _stream(reqs), policy, policy_name=name)
            for rid in outcome.declined_ids:
                seq = outcome.commitment_for(rid).sequence
                request = next(r for r in problem.requests if str(r.request_id) == rid)
                assert not has_placement(problem, fleet, outcome.accepted_before(seq), request)
                checked += 1
    assert checked >= 10, f"only {checked} declines across the corpus; the invariant is barely exercised"


def _small_random_corpus(count: int = 24):
    """A seeded corpus of small contended commingled instances.

    Built to CONTEND: capacities and windows are chosen so the floor binds and
    denials happen. A corpus of slack instances would let every property here
    pass while proving nothing, which is the failure this suite is written
    against.
    """
    import random

    out = []
    for s in range(count):
        rng = random.Random(f"online-corpus/{s}")
        n_veh = rng.choice([1, 2])
        vehicles = [
            _vehicle(amb=rng.choice([1, 2, 3]), wc=1 if k == 0 else rng.choice([0, 1]))
            for k in range(n_veh)
        ]
        reqs = []
        for _ in range(rng.randint(5, 9)):
            start = rng.randrange(0, 60, 5)
            reqs.append(
                _req(
                    open_at=start,
                    close_at=start + rng.choice([0, 5, 10]),
                    ride=rng.choice([15, 20, 25, 30]),
                    wheelchair=rng.random() < 0.4,
                )
            )
        problem = _problem(vehicles, reqs)
        fleet = CommingledFleet.from_problem(problem, wheelchair_footprint=2)
        out.append((problem, fleet, reqs))
    return out


def test_the_corpus_actually_contends_or_this_suite_proves_nothing() -> None:
    """A guard on the guard.

    Every property above is trivially true on a fleet with spare capacity. This
    asserts the generated corpus contains real contention: instances where the
    floor can bind, and instances where a rider was actually turned away. It is
    here because a suite whose instances all avoid the case the constraint exists
    for is the specific way this repository has shipped tests that proved nothing.
    """
    corpus = _small_random_corpus()
    binding = sum(1 for p, f, _r in corpus if f.binds_anywhere(p))
    with_declines = 0
    for problem, fleet, reqs in corpus:
        outcome = run_online(problem, fleet, _stream(reqs), first_fit, policy_name="ff")
        if outcome.declined_ids:
            with_declines += 1
    assert binding >= len(corpus) // 2, f"only {binding}/{len(corpus)} instances can bind the floor"
    assert with_declines >= 6, f"only {with_declines}/{len(corpus)} instances declined anybody"


def test_a_run_is_reproducible_from_the_instance_and_the_arrival_order() -> None:
    problem, fleet, reqs = _contended_problem()
    first = run_online(problem, fleet, _stream(reqs), first_fit, policy_name="ff")
    second = run_online(problem, fleet, _stream(reqs), first_fit, policy_name="ff")
    assert first.commitments == second.commitments
    assert first.solution.model_dump() == second.solution.model_dump()


def test_arrival_order_changes_the_outcome_which_is_the_whole_problem() -> None:
    """Not a defect -- the finding. The arrival order is the one thing the
    operator does not control, and it moves the answer. An exposure number from a
    single order is an anecdote, which is why the benchmark sweeps it."""
    problem, fleet, reqs = _contended_problem()
    forward = run_online(problem, fleet, _stream(reqs), first_fit, policy_name="ff")
    backward = run_online(problem, fleet, _stream(list(reversed(reqs))), first_fit, policy_name="ff")
    assert set(forward.served_ids) != set(backward.served_ids)


def test_arrivals_from_orders_by_booking_instant_and_rejects_a_missing_one() -> None:
    problem, fleet, reqs = _contended_problem()
    booked = [(str(r.request_id), _BASE - timedelta(minutes=i)) for i, r in enumerate(reqs)]
    ordered = arrivals_from(problem, booked)
    assert [str(a.request.request_id) for a in ordered] == [str(r.request_id) for r in reversed(reqs)]
    with pytest.raises(ValueError, match="no booking instant"):
        arrivals_from(problem, booked[:-1])


# ==========================================================================
# The objective the shortfall is measured against.
# ==========================================================================

def test_a_weak_denial_penalty_is_refused_rather_than_measured_around() -> None:
    """A trip-count shortfall is only the optimum's own preference when denying
    any trip costs more than serving every trip could. A silently mis-weighted
    policy would produce a plausible number answering a different question."""
    veh = _vehicle(amb=2, wc=1)
    reqs = [_req(open_at=0, close_at=10, ride=30) for _ in range(4)]
    weak = _problem([veh], reqs, unserved_penalty=5.0, ride_time_weight=1.0)
    with pytest.raises(DenialPenaltyTooWeak):
        assert_denial_dominates(weak)
    strong = _problem([veh], reqs, unserved_penalty=10_000.0, ride_time_weight=1.0)
    assert_denial_dominates(strong)  # does not raise


# ==========================================================================
# The offline optimum: the yardstick, and the relations it must stand in.
# ==========================================================================

@_needs_cpsat
def test_the_offline_optimum_is_never_worse_than_the_online_run() -> None:
    """A cross-check between two entirely separate procedures. The offline model
    sees everything and is proven optimal; a sequential run that beat it would
    mean one of the two is wrong."""
    corpus = _small_random_corpus(12)
    proven = 0
    strictly_better = 0
    for problem, fleet, reqs in corpus:
        online = run_online(problem, fleet, _stream(reqs), first_fit, policy_name="ff")
        offline = solve_commingled_offline(problem, fleet, seed=0, max_deterministic_time=10.0)
        assert offline.served >= len(online.served_ids)
        assert offline.objective <= online.objective + 1e-6
        proven += 1 if offline.proven_optimal else 0
        strictly_better += 1 if offline.served > len(online.served_ids) else 0
    assert proven == len(corpus), "every instance in this corpus should close"
    assert strictly_better >= 3, (
        f"only {strictly_better}/{len(corpus)} instances had a positive gap; a corpus where "
        f"online always matched offline could not distinguish a working measurement from a "
        f"broken one"
    )


@_needs_cpsat
def test_the_offline_optimum_passes_both_independent_checkers() -> None:
    problem, fleet, _reqs = _contended_problem()
    offline = solve_commingled_offline(problem, fleet, seed=0, max_deterministic_time=10.0)
    assert check_commingled(problem, fleet, offline.solution) == []
    assert offline.solution.status is ScheduleRunStatus.OPTIMAL
    assert offline.solution.proven_optimal is True


@_needs_cpsat
def test_the_pool_only_model_is_a_relaxation_and_must_serve_at_least_as_many() -> None:
    """The independent cross-check on the commingled model.

    `packages.decide.cpsat` (unmodified, from ADR-0060) solves the SAME instance
    with the floor constraint dropped. Dropping a constraint is a relaxation, so
    it cannot serve fewer trips. Two independently written models standing in a
    known relation is the cheapest correctness evidence available.

    The relation is also asserted to be non-trivial: on at least one instance the
    relaxation must serve STRICTLY more, or the floor never bound and the check
    would hold for a model that ignored it entirely.
    """
    corpus = _small_random_corpus(12)
    strict = 0
    for problem, fleet, _reqs in corpus:
        offline = solve_commingled_offline(problem, fleet, seed=0, max_deterministic_time=10.0)
        _obj, pool_served, pool_proven = pool_only_relaxation(problem, seed=0, max_deterministic_time=10.0)
        assert pool_proven, "the pool-only model should close on these sizes"
        assert pool_served >= offline.served
        strict += 1 if pool_served > offline.served else 0
    assert strict >= 2, (
        f"the relaxation served strictly more on only {strict}/{len(corpus)} instances; the floor "
        f"constraint is barely binding and this check would pass for a model that dropped it"
    )


# ==========================================================================
# Derived instances: published timing, assigned accessibility labels.
# ==========================================================================

@_needs_archive
def test_a_derived_instance_records_which_of_its_fields_are_assigned() -> None:
    """Provenance is not decoration. An exposure number separated from the
    labelling assumption that produced it is not interpretable, so the assumption
    travels with the instance."""
    inst = derive_commingled_instance(load_zip_instance(_ARCHIVE, "a2-16"), seed=1, vehicle_capacity=2)
    prov = inst.provenance
    assert "Cordeau" in prov.timing_from
    assert prov.accessibility_labels.startswith("ASSIGNED")
    assert "carry NO accessibility attribute" in prov.accessibility_labels
    assert prov.booking_times.startswith("ASSIGNED")
    record = prov.to_record()
    assert set(record) >= {"REAL_timing_from", "ASSIGNED_accessibility_labels", "ASSIGNED_fleet_sizing"}


@_needs_archive
def test_derived_instances_are_reproducible_and_carry_the_exact_cohort_share() -> None:
    """The wheelchair share is exact at every instance size, not merely expected.
    An instance that happened to draw zero wheelchair riders would make the
    accessibility breakdown vacuous."""
    darp = load_zip_instance(_ARCHIVE, "a3-30")
    a = derive_commingled_instance(darp, seed=4, vehicle_capacity=2, wheelchair_share=0.4)
    b = derive_commingled_instance(darp, seed=4, vehicle_capacity=2, wheelchair_share=0.4)
    assert a.problem.model_dump() == b.problem.model_dump()
    assert a.booked_at == b.booked_at
    wc = sum(1 for r in a.problem.requests if r.needs_wheelchair)
    assert wc == round(0.4 * 30) == 12
    different = derive_commingled_instance(darp, seed=5, vehicle_capacity=2, wheelchair_share=0.4)
    assert different.problem.model_dump() != a.problem.model_dump()


@_needs_archive
def test_a_derived_instance_runs_online_and_the_checkers_accept_it() -> None:
    inst = derive_commingled_instance(load_zip_instance(_ARCHIVE, "a3-36"), seed=1, vehicle_capacity=2)
    arrivals = arrivals_from(inst.problem, inst.booked_at)
    assert [str(a.request.request_id) for a in arrivals] == [
        str(r.request_id) for r in inst.arrival_order()
    ]
    outcome = run_online(inst.problem, inst.fleet, arrivals, first_fit, policy_name="first-fit")
    assert check_commingled(inst.problem, inst.fleet, outcome.solution) == []
    assert inst.fleet.binds_anywhere(inst.problem)
    assert outcome.declined_ids, "a3-36 at capacity 2 is a contended instance; something must be turned away"
