"""Program F conformance: the CP-SAT routing backend, the exact scheduler, and
the DARP portfolio.

The claim this file has to earn is the load-bearing one in
`metis.decide.cpsat_darp`: that `lower_bound` is a RIGOROUS lower bound on the
true (unrounded, Euclidean) optimum. Everything the benchmark says about
optimality gaps rests on it, so it is tested three independent ways:

- against EXHAUSTIVE ENUMERATION on instances small enough to brute-force, where
  the true optimum is known by construction;
- against the PUBLISHED optima of the acquired Cordeau instances, which the model
  must never undercut;
- against every checker-verified routing any other strategy produces, which must
  never come in below the bound.

Also here: `exact_schedule`, the difference-constraint scheduler added because
the existing eight-step heuristic is sound but INCOMPLETE. That incompleteness is
pinned with a concrete instance rather than asserted, since it is the entire
reason the new routine exists.

Instances are synthetic (generated here) or the acquired Cordeau academic
benchmark set. Both support ALGORITHMIC claims only. Nothing in this file is
evidence about any real operator's service.
"""

from __future__ import annotations

import itertools
import random

import pytest

from metis.decide.capability import SolverCapability, ortools_capability
from metis.decide.darp_ir import DarpInstance, DarpRoute, DarpSolution, DarpVisit
from metis.decide.darp_loader import find_benchmark_archive, load_zip_instance, parse_instance
from metis.decide.darp_solver import route_distance, schedule_route, solve_darp
from metis.decide.cpsat_darp import exact_schedule, solve_darp_cpsat
from metis.decide.feasibility import check_darp_feasibility, darp_objective
from metis.decide.portfolio import PortfolioContradiction, solve_darp_portfolio

_CAP = ortools_capability()
_needs_cpsat = pytest.mark.skipif(not _CAP.available, reason=f"OR-Tools unavailable: {_CAP.detail}")
_ARCHIVE = find_benchmark_archive()
_needs_archive = pytest.mark.skipif(_ARCHIVE is None, reason="Cordeau DARP benchmark archive not acquired")

# The published single-depot Cordeau optima this suite checks against. Kept as a
# literal here (not read from aletheia/benchmarks/) so a corrupted benchmark file cannot
# quietly relax the assertion it is supposed to be constrained by.
_PUBLISHED_OPTIMA = {"a2-16": 294.25, "a2-20": 344.83, "a3-18": 300.48, "a4-16": 282.68}
# Those values are printed to two decimal places in the source table, so the true
# optimum lies within half a unit of the last place. Our own bound legitimately
# sits inside that band (a3-18: we prove 300.48316, the table says 300.48), and
# an assertion tighter than the data's own precision would fail on arithmetic
# rather than on a defect.
_PUBLISHED_ROUNDING = 0.005

# A sequence the eight-step heuristic scheduler REJECTS although a feasible
# schedule exists. Found by enumeration; pinned so the incompleteness that
# motivated `exact_schedule` is a fact in the suite, not a claim in a docstring.
_INCOMPLETE_CASE = """1 3 480 3 40
0 0.0 0.0 0 0 0 480
1 -4.223 -6.349 3 1 0 480
2 -1.663 -5.52 3 1 0 480
3 -6.936 -1.575 3 1 0 480
4 6.687 4.807 3 -1 108 124
5 4.243 -4.449 3 -1 154 177
6 0.587 -3.573 3 -1 33 84
7 0.0 0.0 0 0 0 480
"""
_INCOMPLETE_SEQ = [0, 3, 6, 1, 4, 2, 5, 7]


def _one_route_solution(instance: DarpInstance, seq, begin) -> DarpSolution:
    return DarpSolution(
        instance_name=instance.name,
        num_requests=instance.num_requests,
        routes=(DarpRoute(
            vehicle=0,
            visits=tuple(DarpVisit(node_index=s, begin_service=begin[k]) for k, s in enumerate(seq)),
        ),),
        status="probe", objective=None, served_requests=(),
        solver_name="test", solver_version="0", seed=0,
    )


def _schedule_is_accepted(instance: DarpInstance, seq, begin) -> bool:
    """Judged by the INDEPENDENT checker, never by the scheduler that produced it."""
    return not check_darp_feasibility(instance, _one_route_solution(instance, seq, begin))


def _synth_instance(rng: random.Random, *, n: int = 3, K: int = 1, Q: int = 3, L: float = 40, T: float = 480) -> DarpInstance:
    """A small random Cordeau-format instance: one depot at the origin, pickups
    with open windows, drop-offs with tight ones (the shape that makes ride-time
    and window interaction bite)."""
    lines = [f"{K} {n} {T} {Q} {L}"]
    pts = [(0.0, 0.0)]
    pts += [(round(rng.uniform(-8, 8), 3), round(rng.uniform(-8, 8), 3)) for _ in range(2 * n)]
    pts += [(0.0, 0.0)]
    for i, (x, y) in enumerate(pts):
        if i in (0, 2 * n + 1):
            lines.append(f"{i} {x} {y} 0 0 0 {T}")
        elif i <= n:
            lines.append(f"{i} {x} {y} 3 1 0 {T}")
        else:
            s = rng.randint(20, 300)
            lines.append(f"{i} {x} {y} 3 -1 {s} {s + rng.randint(10, 60)}")
    return parse_instance("\n".join(lines) + "\n", name=f"synth-{n}-{K}")


def _cheapest_single_route(instance: DarpInstance, reqs: list[int]) -> float | None:
    """Cheapest feasible one-vehicle route serving exactly `reqs`, or None if none
    exists. An empty assignment costs 0 -- an unused vehicle stays at the depot,
    which is what the CP-SAT model allows too."""
    if not reqs:
        return 0.0
    nodes = [instance.pickup_index(r) for r in reqs] + [instance.dropoff_index(r) for r in reqs]
    best = None
    for perm in itertools.permutations(nodes):
        if any(perm.index(instance.pickup_index(r)) > perm.index(instance.dropoff_index(r)) for r in reqs):
            continue  # a drop-off before its pickup
        seq = [instance.depot_start] + list(perm) + [instance.depot_end]
        begin = exact_schedule(instance, seq)
        if begin is None or not _schedule_is_accepted(instance, seq, begin):
            continue
        cost = route_distance(instance, seq)
        if best is None or cost < best - 1e-12:
            best = cost
    return best


def _brute_force_optimum(instance: DarpInstance) -> float | None:
    """The TRUE optimum by exhaustive enumeration, for K in {1, 2}.

    Independent of CP-SAT in every respect: it enumerates the request-to-vehicle
    split and the orderings directly, and a candidate only counts once the
    INDEPENDENT checker accepts its schedule. Only tractable for tiny n, which is
    exactly what it is for.

    Covering K=2 is not decoration. With one vehicle the model's pickup/drop-off
    same-vehicle constraint is VACUOUS -- there is nowhere else to put a node --
    so a K=1-only comparison cannot detect its removal, and a mutation check
    proved exactly that."""
    n, K = instance.num_requests, instance.num_vehicles
    assert K in (1, 2), "brute force covers one- and two-vehicle instances only"
    best = None
    for mask in range(1 << n):
        first = [r for r in range(1, n + 1) if not (mask >> (r - 1)) & 1]
        second = [r for r in range(1, n + 1) if (mask >> (r - 1)) & 1]
        if K == 1 and second:
            continue
        c0 = _cheapest_single_route(instance, first)
        if c0 is None:
            continue
        c1 = _cheapest_single_route(instance, second)
        if c1 is None:
            continue
        total = c0 + c1
        if best is None or total < best - 1e-12:
            best = total
    return best


# ==========================================================================
# 1. exact_schedule -- the difference-constraint scheduler
# ==========================================================================

def test_exact_scheduler_solves_a_sequence_the_eight_step_heuristic_rejects() -> None:
    """The pinned incompleteness. `schedule_route` is SOUND but not COMPLETE: it
    returns None here even though a feasible schedule exists, which is why
    `exact_schedule` had to be written. The independent checker settles it."""
    inst = parse_instance(_INCOMPLETE_CASE, name="incomplete-case")

    assert schedule_route(inst, _INCOMPLETE_SEQ) is None  # the heuristic gives up
    begin = exact_schedule(inst, _INCOMPLETE_SEQ)
    assert begin is not None
    assert _schedule_is_accepted(inst, _INCOMPLETE_SEQ, begin)  # and it was right to


def test_exact_scheduler_absorbs_waiting_instead_of_giving_up() -> None:
    """The completeness that matters, in miniature. Request 1's drop-off window
    opens at 108 and the ride ceiling is 40, so boarding at the earliest possible
    moment (~7.6 minutes out) would blow the ride limit. The exact scheduler must
    DELAY the pickup to 65 so the ride is exactly 40 -- a naive as-early schedule
    cannot find this."""
    inst = parse_instance(_INCOMPLETE_CASE, name="incomplete-case")
    begin = exact_schedule(inst, [0, 1, 4, 7])
    assert begin is not None
    assert begin[1] == pytest.approx(65.0, abs=1e-6)   # pickup deliberately delayed
    assert begin[2] == pytest.approx(108.0, abs=1e-6)  # drop-off at the window's open
    assert _schedule_is_accepted(inst, [0, 1, 4, 7], begin)


def test_exact_scheduler_rejects_a_genuinely_impossible_sequence() -> None:
    """Completeness cuts both ways: it must still say no when the answer is no.
    Request 3's drop-off (node 6) closes at 84, but this ordering puts it after
    request 1's drop-off (node 4), which cannot begin before 108. No amount of
    waiting or delaying repairs that -- and the scheduler must not pretend it
    can."""
    inst = parse_instance(_INCOMPLETE_CASE, name="incomplete-case")
    assert exact_schedule(inst, [0, 1, 4, 3, 6, 7]) is None
    assert exact_schedule(inst, [0, 2, 5, 3, 6, 7]) is None


def test_exact_scheduler_rejects_a_capacity_overload_no_timing_can_fix() -> None:
    tight = _INCOMPLETE_CASE.replace("1 3 480 3 40", "1 3 480 1 40", 1)  # capacity 1
    inst = parse_instance(tight, name="cap1")
    assert exact_schedule(inst, [0, 1, 2, 4, 5, 3, 6, 7]) is None  # two aboard at once


def test_exact_scheduler_rejects_a_dropoff_placed_before_its_pickup() -> None:
    inst = parse_instance(_INCOMPLETE_CASE, name="incomplete-case")
    assert exact_schedule(inst, [0, 4, 1, 7]) is None


def test_property_every_schedule_the_exact_scheduler_returns_is_accepted() -> None:
    """Soundness over many random sequences: whatever it returns must satisfy the
    INDEPENDENT checker. A scheduler that returned optimistic times would be
    caught here, by code that never saw the scheduler.

    Deliberately NOT parametrized per trial: many random sequences are simply
    infeasible, so a per-trial test would have to tolerate zero schedules checked
    and its assertion would be vacuous. Aggregating lets the test demand a real
    minimum of accepted schedules -- so it fails both if a schedule is wrong AND
    if the scheduler quietly stops producing any."""
    checked = 0
    duration_bound_cases = 0
    for trial in range(40):
        rng = random.Random(7000 + trial)
        # HALF the instances get a max_route_duration far tighter than the depot
        # window. Without that, T is never binding (the depot window alone
        # enforces it) and the scheduler's depot-departure push -- the step that
        # absorbs waiting into the duration -- is dead code the property cannot
        # see. A mutation check proved that gap was real.
        tight = trial % 2 == 1
        inst = _synth_instance(rng, n=3, T=240 if tight else 480)
        n = inst.num_requests
        perms = [p for p in itertools.permutations(range(1, 2 * n + 1))
                 if all(p.index(r) < p.index(n + r) for r in range(1, n + 1))]
        for perm in perms:
            seq = [inst.depot_start] + list(perm) + [inst.depot_end]
            begin = exact_schedule(inst, seq)
            if begin is None:
                continue
            assert _schedule_is_accepted(inst, seq, begin), f"unsound schedule for {seq}"
            checked += 1
            if tight:
                duration_bound_cases += 1
    # Most random orderings genuinely are not schedulable, so the floor is set
    # below the measured count but far above zero: the test fails both if a
    # schedule is unsound AND if the scheduler quietly stops producing any.
    assert checked >= 180, f"only {checked} schedules were produced; the property barely ran"
    assert duration_bound_cases >= 50, (
        f"only {duration_bound_cases} schedules came from tight-duration instances; "
        f"the max-route-duration branch is not being exercised"
    )


def test_exact_scheduler_is_at_least_as_complete_as_the_heuristic() -> None:
    """Anywhere the eight-step heuristic succeeds, the exact scheduler must too.
    A 'complete' routine that lost cases the heuristic solved would be a
    regression wearing an upgrade's name."""
    both, heuristic_only = 0, 0
    for trial in range(60):
        rng = random.Random(8000 + trial)
        inst = _synth_instance(rng, n=3)
        n = inst.num_requests
        for perm in itertools.permutations(range(1, 2 * n + 1)):
            if any(perm.index(r) > perm.index(n + r) for r in range(1, n + 1)):
                continue
            seq = [inst.depot_start] + list(perm) + [inst.depot_end]
            if schedule_route(inst, seq) is not None:
                if exact_schedule(inst, seq) is not None:
                    both += 1
                else:
                    heuristic_only += 1
    assert both > 0  # the comparison actually exercised something
    assert heuristic_only == 0


# ==========================================================================
# 2. the CP-SAT bound, against exhaustive enumeration
# ==========================================================================

@_needs_cpsat
@pytest.mark.parametrize("K", [1, 2])
@pytest.mark.parametrize("trial", range(12))
def test_property_cpsat_bound_never_exceeds_the_brute_forced_true_optimum(trial: int, K: int) -> None:
    """THE load-bearing property. On instances small enough to enumerate, the
    true optimum is known exactly; the CP-SAT lower bound must never be above it,
    or every gap the benchmark reports is overstated.

    Run at K=1 AND K=2: the same-vehicle pairing constraint is vacuous with one
    vehicle, so only the two-vehicle case can catch its loss."""
    rng = random.Random(3000 + trial)
    inst = _synth_instance(rng, n=3, K=K)
    true_opt = _brute_force_optimum(inst)
    outcome = solve_darp_cpsat(inst, seed=trial, max_deterministic_time=15.0)

    if true_opt is None:
        pytest.skip("instance admits no feasible routing at all")
    assert outcome.lower_bound is not None
    assert outcome.lower_bound <= true_opt + 1e-9, (
        f"bound {outcome.lower_bound} EXCEEDS the true optimum {true_opt} -- the "
        f"relaxation argument is broken"
    )
    # And when CP-SAT closes the model, its verified route must BE the optimum.
    if outcome.proved_model_optimal and outcome.solution is not None:
        assert outcome.objective == pytest.approx(true_opt, abs=1e-6)
        assert outcome.certified_optimal is True


@_needs_cpsat
@pytest.mark.parametrize("trial", range(8))
def test_property_every_request_is_picked_up_and_dropped_off_by_one_vehicle(trial: int) -> None:
    """The same-vehicle pairing constraint, tested where it can actually bind.

    Splitting a request across two vehicles is strictly cheaper for the model
    (each vehicle carries half the detour), so if the constraint were dropped
    CP-SAT would do it -- and the independent checker would then reject the
    routing entirely, leaving no verified solution. Requiring one here is what
    makes the constraint load-bearing in the suite."""
    rng = random.Random(4400 + trial)
    inst = _synth_instance(rng, n=3, K=2)
    if _brute_force_optimum(inst) is None:
        pytest.skip("instance admits no feasible routing at all")
    outcome = solve_darp_cpsat(inst, seed=trial, max_deterministic_time=15.0)

    assert outcome.solution is not None, f"no verified routing: {outcome.detail}"
    assert check_darp_feasibility(inst, outcome.solution) == []
    vehicle_of: dict[int, int] = {}
    for route in outcome.solution.routes:
        for visit in route.visits:
            if visit.node_index not in (inst.depot_start, inst.depot_end):
                vehicle_of[visit.node_index] = route.vehicle
    for r in range(1, inst.num_requests + 1):
        p, d = inst.pickup_index(r), inst.dropoff_index(r)
        assert (p in vehicle_of) == (d in vehicle_of), f"request {r} half-served"
        if p in vehicle_of:
            assert vehicle_of[p] == vehicle_of[d], (
                f"request {r} picked up by vehicle {vehicle_of[p]} but dropped off by "
                f"{vehicle_of[d]}"
            )


def test_certified_optimal_is_false_when_the_incumbent_is_above_the_bound() -> None:
    """Pins the certification predicate itself, hand-built so no solver run is
    involved. A `certified_optimal` that ignored the bound would be the single
    most dangerous defect in this module -- it is the flag a caller would quote
    as 'proven optimal' -- so it is asserted in both directions."""
    from metis.decide.cpsat_darp import CpSatDarpOutcome

    def _outcome(objective: float | None, bound: float | None, tol: float) -> CpSatDarpOutcome:
        solution = None
        if objective is not None:
            solution = DarpSolution(
                instance_name="x", num_requests=1, routes=(), status="feasible",
                objective=objective, served_requests=(1,), solver_name="t",
                solver_version="0", seed=0,
            )
        return CpSatDarpOutcome(
            instance_name="x", solution=solution, lower_bound=bound, raw_status="FEASIBLE",
            proved_model_optimal=False, sequence_rejected=False, wall_time_s=0.0,
            deterministic_time=0.0, detail="", lattice_tolerance=tol,
        )

    # An open gap is NOT a certificate.
    assert _outcome(300.0, 290.0, 3.4e-5).certified_optimal is False
    # Even a hair above the bound, beyond the stated lattice tolerance, is not.
    assert _outcome(290.001, 290.0, 3.4e-5).certified_optimal is False
    # Meeting the bound within the lattice tolerance is.
    assert _outcome(290.00001, 290.0, 3.4e-5).certified_optimal is True
    assert _outcome(290.0, 290.0, 3.4e-5).certified_optimal is True
    # No incumbent, or no bound, certifies nothing.
    assert _outcome(None, 290.0, 3.4e-5).certified_optimal is False
    assert _outcome(290.0, None, 3.4e-5).certified_optimal is False


@_needs_cpsat
def test_cpsat_route_is_always_re_verified_by_the_independent_checker() -> None:
    rng = random.Random(31)
    inst = _synth_instance(rng, n=3, K=1)
    outcome = solve_darp_cpsat(inst, seed=0, max_deterministic_time=15.0)
    if outcome.solution is None:
        pytest.skip("CP-SAT produced no exactly-verifiable routing for this instance")
    assert check_darp_feasibility(inst, outcome.solution) == []
    assert outcome.solution.status in {"feasible", "incomplete"}
    assert outcome.solution.status != "optimal"  # never claimed on the model's say-so


@_needs_cpsat
def test_a_coarser_lattice_gives_a_weaker_but_still_valid_bound() -> None:
    """The lattice is a stated parameter, and coarsening it must only ever LOSE
    tightness -- never produce a bound above a finer lattice's answer plus its
    own tolerance. If a coarse lattice could overstate, the bound would depend on
    a tuning knob rather than on the instance."""
    rng = random.Random(77)
    inst = _synth_instance(rng, n=3, K=1)
    true_opt = _brute_force_optimum(inst)
    if true_opt is None:
        pytest.skip("instance admits no feasible routing")
    coarse = solve_darp_cpsat(inst, seed=0, max_deterministic_time=15.0, scale=1000)
    fine = solve_darp_cpsat(inst, seed=0, max_deterministic_time=15.0, scale=1_000_000)
    assert coarse.lower_bound <= true_opt + 1e-9
    assert fine.lower_bound <= true_opt + 1e-9
    assert coarse.lower_bound <= fine.lower_bound + 1e-6  # coarser is never tighter
    assert coarse.lattice_tolerance > fine.lattice_tolerance


# ==========================================================================
# 3. against the published Cordeau optima
# ==========================================================================

@_needs_cpsat
@_needs_archive
@pytest.mark.parametrize("name", sorted(_PUBLISHED_OPTIMA))
def test_cpsat_bound_never_undercuts_a_published_optimum_illegally(name: str) -> None:
    """A lower bound may sit BELOW a published optimum (it is a bound), but it
    may never sit ABOVE one -- that would assert the published proven optimum is
    infeasible, i.e. that Cordeau (2006) is wrong. Any such result is our bug."""
    inst = load_zip_instance(_ARCHIVE, name)
    # A small budget on purpose. The bound assertion below is valid at ANY
    # budget -- a shorter search gives a weaker bound, not a wrong one -- and a
    # generous one cost 344s on a4-16 alone. The instances that CAN close still
    # close, so the stronger reproduces-the-published-figure branch still fires.
    outcome = solve_darp_cpsat(inst, seed=1, max_deterministic_time=5.0)
    published = _PUBLISHED_OPTIMA[name]
    assert outcome.lower_bound is not None
    ceiling = published + _PUBLISHED_ROUNDING + outcome.lattice_tolerance
    assert outcome.lower_bound <= ceiling, (
        f"{name}: our lower bound {outcome.lower_bound} exceeds the published proven "
        f"optimum {published} by more than its own printed precision; the relaxation "
        f"argument or the model is wrong"
    )
    # The far stronger claim, asserted whenever CP-SAT closed the model: our
    # exactly-verified route rounds to the published figure. That is the whole
    # pipeline -- loader, distance convention, model, scheduler, checker --
    # agreeing with the literature to its stated precision.
    if outcome.solution is not None and outcome.certified_optimal:
        assert round(darp_objective(inst, outcome.solution), 2) == published


@_needs_cpsat
@_needs_archive
def test_cpsat_independently_reproduces_the_published_optimum_for_a2_16() -> None:
    """The strongest available end-to-end evidence that the model, the loader,
    the distance convention and the checker all agree with the literature: an
    exactly-verified routing whose distance matches the published proven optimum
    of 294.25, with a self-computed bound that certifies it."""
    inst = load_zip_instance(_ARCHIVE, "a2-16")
    outcome = solve_darp_cpsat(inst, seed=1, max_deterministic_time=45.0)

    assert outcome.solution is not None, f"expected a verified routing, got: {outcome.detail}"
    assert check_darp_feasibility(inst, outcome.solution) == []
    assert len(outcome.solution.served_requests) == 16
    assert darp_objective(inst, outcome.solution) == pytest.approx(294.25, abs=0.01)
    assert outcome.certified_optimal is True


# ==========================================================================
# 4. the DARP portfolio
# ==========================================================================

@_needs_cpsat
@_needs_archive
def test_portfolio_prefers_the_cpsat_route_over_the_heuristic_on_a2_16() -> None:
    """On this instance the portfolio genuinely changes the answer: the LNS
    returns ~318 and CP-SAT returns the optimum ~294.25. The portfolio must
    return the better VERIFIED route and report the loser's number too."""
    inst = load_zip_instance(_ARCHIVE, "a2-16")
    solution, report = solve_darp_portfolio(
        inst, seed=1, lns_iterations=50, cpsat_deterministic_time=45.0
    )
    assert report.winner == "cpsat-darp"
    assert solution is not None
    assert darp_objective(inst, solution) == pytest.approx(294.25, abs=0.01)
    lns = report.run("lns")
    assert lns.ran and lns.objective is not None
    assert lns.objective > darp_objective(inst, solution)  # the heuristic really did lose
    assert report.best_bound is not None
    assert report.portfolio_gap is not None and report.portfolio_gap >= -1e-9
    assert report.deterministic is True


def test_darp_portfolio_runs_without_ortools_and_records_why(monkeypatch) -> None:
    """Injected unavailability: the routing portfolio must still return a
    heuristic answer and name the missing dependency."""
    monkeypatch.setattr(
        "metis.decide.portfolio.ortools_capability",
        lambda: SolverCapability("ortools-cpsat", False, None, "ImportError: injected for test"),
    )
    inst = _synth_instance(random.Random(5), n=3, K=1)
    solution, report = solve_darp_portfolio(inst, seed=0, lns_iterations=30)

    assert "cpsat-darp" in report.strategies_unavailable
    assert "injected for test" in report.run("cpsat-darp").detail
    assert report.best_bound is None  # no bound without the exact solver -- stated, not faked
    assert report.portfolio_gap is None
    assert report.winner in {"regret-construction", "lns"}
    if solution is not None:
        assert check_darp_feasibility(inst, solution) == []


@_needs_cpsat
def test_darp_portfolio_is_deterministic_for_a_fixed_seed() -> None:
    inst = _synth_instance(random.Random(12), n=3, K=1)
    first_sol, first_rep = solve_darp_portfolio(inst, seed=4, lns_iterations=40, cpsat_deterministic_time=10.0)
    second_sol, second_rep = solve_darp_portfolio(inst, seed=4, lns_iterations=40, cpsat_deterministic_time=10.0)

    assert first_rep.deterministic is True
    assert first_rep.winner == second_rep.winner
    assert first_rep.best_bound == second_rep.best_bound
    assert [r.objective for r in first_rep.runs] == [r.objective for r in second_rep.runs]
    if first_sol is not None and second_sol is not None:
        assert first_sol.to_record() == second_sol.to_record()


def test_a_routing_cheaper_than_a_rigorous_bound_raises_a_contradiction() -> None:
    """Hand-built impossibility: a checker-verified routing whose distance is
    below a claimed lower bound. One of the two must be wrong, and the portfolio
    must refuse to pick a winner rather than silently prefer the cheaper number."""
    from metis.decide.portfolio import _assert_no_darp_contradiction

    inst = parse_instance(_INCOMPLETE_CASE, name="contradiction-case")
    seq = [0, 1, 2, 3, 6, 4, 5, 7]
    begin = exact_schedule(inst, seq)
    if begin is None:
        seq = [0, 3, 6, 1, 4, 2, 5, 7]
        begin = exact_schedule(inst, seq)
    assert begin is not None
    real = route_distance(inst, seq)
    solution = DarpSolution(
        instance_name=inst.name, num_requests=inst.num_requests,
        routes=(DarpRoute(vehicle=0, visits=tuple(
            DarpVisit(node_index=s, begin_service=begin[k]) for k, s in enumerate(seq))),),
        status="feasible", objective=real, served_requests=(1, 2, 3),
        solver_name="hand-built", solver_version="0", seed=0,
    )
    # A bound well above the verified route's true distance: impossible.
    with pytest.raises(PortfolioContradiction, match="below"):
        _assert_no_darp_contradiction(inst, [("hand-built", solution)], [("liar", real + 50.0)])


def test_a_consistent_bound_does_not_raise() -> None:
    """Positive control for the contradiction check: a bound BELOW the verified
    route is the normal case and must pass, or the check above would be satisfied
    by a function that always raised."""
    from metis.decide.portfolio import _assert_no_darp_contradiction

    inst = parse_instance(_INCOMPLETE_CASE, name="consistent-case")
    seq = [0, 3, 6, 1, 4, 2, 5, 7]
    begin = exact_schedule(inst, seq)
    assert begin is not None
    real = route_distance(inst, seq)
    solution = DarpSolution(
        instance_name=inst.name, num_requests=inst.num_requests,
        routes=(DarpRoute(vehicle=0, visits=tuple(
            DarpVisit(node_index=s, begin_service=begin[k]) for k, s in enumerate(seq))),),
        status="feasible", objective=real, served_requests=(1, 2, 3),
        solver_name="hand-built", solver_version="0", seed=0,
    )
    _assert_no_darp_contradiction(inst, [("hand-built", solution)], [("honest", real - 10.0)])


@_needs_cpsat
@pytest.mark.parametrize("trial", range(10))
def test_property_no_verified_routing_ever_beats_the_bound(trial: int) -> None:
    """The cross-check the portfolio exists to buy, over random instances: the
    heuristic's verified route and CP-SAT's rigorous bound must be consistent.
    `solve_darp_portfolio` raises if they are not, so reaching the assertions is
    itself the evidence."""
    rng = random.Random(6000 + trial)
    inst = _synth_instance(rng, n=3, K=1)
    solution, report = solve_darp_portfolio(
        inst, seed=trial, lns_iterations=40, cpsat_deterministic_time=10.0
    )
    if report.best_bound is None or solution is None or solution.status != "feasible":
        pytest.skip("no bound or no complete routing for this instance")
    tolerance = (2 * inst.num_requests + inst.num_vehicles) / 1_000_000 + 1e-9
    assert darp_objective(inst, solution) >= report.best_bound - tolerance
    for run in report.runs:
        if run.objective is not None and run.verified:
            assert run.objective >= report.best_bound - tolerance


@_needs_cpsat
@_needs_archive
def test_lns_and_cpsat_never_contradict_on_a_real_instance() -> None:
    inst = load_zip_instance(_ARCHIVE, "a3-18")
    heuristic = solve_darp(inst, seed=2, max_iterations=100, time_limit_s=None)
    outcome = solve_darp_cpsat(inst, seed=2, max_deterministic_time=5.0)
    assert check_darp_feasibility(inst, heuristic) == []
    if heuristic.status == "feasible" and outcome.lower_bound is not None:
        assert darp_objective(inst, heuristic) >= outcome.lower_bound - outcome.lattice_tolerance
