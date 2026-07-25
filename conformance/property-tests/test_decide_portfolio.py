"""Program F conformance: the solver PORTFOLIO and its CP-SAT backend.

`packages.decide.solver` shipped one hand-rolled search and recorded a portfolio
as Specified. These are the contract properties of the portfolio that replaced
that aspiration:

1. CAPABILITY, NOT CRASH. A strategy whose optional solver is missing is recorded
   as unavailable-with-a-reason and skipped; the portfolio still returns an
   answer. Proven by INJECTING the unavailable capability rather than by
   uninstalling OR-Tools, so the skip path is exercised on a machine where the
   wheel is present.
2. TWO INDEPENDENT SEARCHES AGREE. CP-SAT and the branch-and-bound discretize the
   problem identically, so whenever both prove optimality they must report the
   SAME objective. Disagreement is a bug in one of them; the test drives many
   random instances to look for it.
3. THE PORTFOLIO IS STRICTLY STRONGER THAN ITS PARTS. There are instances where
   the branch-and-bound exhausts its node budget and reports TIMEOUT while CP-SAT
   proves an optimum. The portfolio must return the proof.
4. DETERMINISM IS REAL AND TESTED. Same problem, same seed, deterministic
   budgets -> byte-identical solution AND the same winner. If the answer moved
   with machine load, every benchmark number would be unreproducible.
5. NOTHING WINS WITHOUT INDEPENDENT VERIFICATION. A strategy that returns an
   infeasible answer is disqualified, not returned.
6. PROVERS MAY NOT CONTRADICT EACH OTHER. Two proofs that disagree raise, rather
   than being silently tie-broken.

Every test here runs on synthetic instances. Nothing in this file supports an
operational claim.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from packages.canonical import PolicyId, RequestId, TenantId, VehicleId, new_id
from packages.canonical.vocab import ReasonCode, ScheduleRunStatus
from packages.decide import (
    DecisionPolicy,
    DecisionProblem,
    DecisionVehicle,
    RideRequest,
    is_feasible,
    solve,
)
from packages.decide.capability import SolverCapability, SolverUnavailable, ortools_capability
from packages.decide.cpsat import CPSAT_SOLVER_NAME, solve_cpsat, solve_cpsat_detailed
from packages.decide.portfolio import (
    PortfolioContradiction,
    _assert_no_decision_contradiction,
    solve_portfolio,
)

_CAP = ortools_capability()
_needs_cpsat = pytest.mark.skipif(not _CAP.available, reason=f"OR-Tools unavailable: {_CAP.detail}")

_BASE = datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc)


def _at(minute: int) -> datetime:
    return _BASE + timedelta(minutes=minute)


def _policy(**kw) -> DecisionPolicy:
    return DecisionPolicy(policy_id=new_id(PolicyId), name="portfolio-test", **kw)


def _vehicle(amb: int, wc: int, shift_minutes: int = 240) -> DecisionVehicle:
    return DecisionVehicle(
        vehicle_id=new_id(VehicleId),
        capacity_ambulatory=amb,
        capacity_wheelchair=wc,
        shift_start=_BASE,
        shift_end=_BASE + timedelta(minutes=shift_minutes),
    )


def _random_instance(rng: random.Random) -> DecisionProblem:
    vehicles = tuple(_vehicle(rng.randint(1, 3), rng.randint(0, 2)) for _ in range(rng.randint(1, 3)))
    requests = []
    for _ in range(rng.randint(1, 5)):
        start = rng.randint(0, 120)
        requests.append(
            RideRequest(
                request_id=new_id(RequestId),
                pickup_window_start=_at(start),
                pickup_window_end=_at(start + rng.randint(5, 40)),
                dropoff_window_end=_at(start + rng.randint(40, 120)),
                needs_wheelchair=rng.random() < 0.3,
                party_size=rng.randint(1, 2),
                nominal_ride_time_minutes=rng.randint(5, 40),
                max_ride_time_minutes=rng.randint(20, 90),
                must_serve=rng.random() < 0.5,
            )
        )
    return DecisionProblem(
        tenant_id=new_id(TenantId), policy=_policy(), vehicles=vehicles, requests=tuple(requests)
    )


def _budget_starved_problem() -> DecisionProblem:
    """Six interchangeable requests on one single-seat vehicle with a 3-node
    search budget: the branch-and-bound cannot finish, CP-SAT finds it easy."""
    return DecisionProblem(
        tenant_id=new_id(TenantId),
        policy=_policy(max_search_nodes=3),
        vehicles=(_vehicle(1, 0),),
        requests=tuple(
            RideRequest(
                request_id=new_id(RequestId),
                pickup_window_start=_at(0),
                pickup_window_end=_at(120),
                dropoff_window_end=_at(180),
                nominal_ride_time_minutes=20,
                max_ride_time_minutes=60,
                must_serve=False,
            )
            for _ in range(6)
        ),
    )


# --- 1. capability, not crash --------------------------------------------

def test_capability_probe_reports_a_real_reason_either_way() -> None:
    cap = ortools_capability()
    assert cap.name == "ortools-cpsat"
    assert isinstance(cap.available, bool)
    assert cap.detail  # never an empty string: the report copies this verbatim
    if cap.available:
        assert cap.version and cap.version != "unknown"
    else:
        assert cap.version is None


def test_capability_reports_unavailable_when_the_import_genuinely_fails() -> None:
    """Exercises `capability.py`'s REAL except branch.

    The other unavailability tests monkeypatch the capability object, which
    proves the portfolio handles a False verdict but never runs the code that
    PRODUCES one -- on this machine the wheel imports fine, so that branch is
    dead code the suite would otherwise never touch. Here the import is blocked
    at the meta-path level (and ortools evicted from `sys.modules`, or the cached
    module would satisfy the import without consulting the finder), so the probe
    takes a genuine ImportError and must report it verbatim.
    """
    import importlib.abc
    import sys

    class _BlockOrTools(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name == "ortools" or name.startswith("ortools."):
                raise ImportError("simulated: no ortools wheel for this interpreter")
            return None

    blocker = _BlockOrTools()
    evicted = {k: v for k, v in sys.modules.items() if k == "ortools" or k.startswith("ortools.")}
    for key in evicted:
        del sys.modules[key]
    sys.meta_path.insert(0, blocker)
    try:
        cap = ortools_capability(refresh=True)
    finally:
        sys.meta_path.remove(blocker)
        sys.modules.update(evicted)
        ortools_capability(refresh=True)  # restore this process's real verdict

    assert cap.available is False
    assert cap.version is None
    assert "simulated: no ortools wheel" in cap.detail  # the loader's own words, not a paraphrase
    # And the cache really was restored, so no later test inherits the fake verdict.
    assert ortools_capability().available == _CAP.available


def test_portfolio_skips_an_unavailable_strategy_cleanly(monkeypatch) -> None:
    """INJECTED unavailability. OR-Tools is installed here, so the only way to
    exercise the skip path -- the path that keeps a machine without the wheel
    green -- is to make the probe report unavailable and check the portfolio
    still answers, records the reason, and does not raise."""
    monkeypatch.setattr(
        "packages.decide.portfolio.ortools_capability",
        lambda: SolverCapability(
            name="ortools-cpsat", available=False, version=None,
            detail="ImportError: injected for test",
        ),
    )
    problem = _budget_starved_problem()
    solution, report = solve_portfolio(problem, seed=1)

    assert "cpsat" in report.strategies_unavailable
    assert "cpsat" not in report.strategies_available
    cpsat_run = report.run("cpsat")
    assert cpsat_run is not None and cpsat_run.ran is False
    assert "injected for test" in cpsat_run.detail  # the reason survives into the report
    # The portfolio still produced a usable, verified answer from what remained.
    assert report.winner in {"exact-bnb", "greedy"}
    assert is_feasible(problem, solution)


def test_calling_the_backend_directly_without_ortools_raises_a_named_error(monkeypatch) -> None:
    monkeypatch.setattr(
        "packages.decide.cpsat.ortools_capability",
        lambda: SolverCapability("ortools-cpsat", False, None, "ImportError: injected"),
    )
    with pytest.raises(SolverUnavailable, match="OR-Tools"):
        solve_cpsat(_budget_starved_problem(), seed=0)


# --- 2. two independent searches agree ------------------------------------

@_needs_cpsat
@pytest.mark.parametrize("trial", range(40))
def test_property_cpsat_and_branch_and_bound_agree_when_both_prove_optimality(trial: int) -> None:
    """The two backends search the SAME discretized candidate set by
    construction, so a proven optimum is a proven optimum. Any difference beyond
    float noise is a modelling bug in one of them."""
    problem = _random_instance(random.Random(trial))
    bnb = solve(problem, seed=trial)
    cp = solve_cpsat_detailed(problem, seed=trial, max_deterministic_time=5.0)

    assert is_feasible(problem, cp.solution)  # independently checked, always
    if bnb.status is ScheduleRunStatus.OPTIMAL and cp.solution.status is ScheduleRunStatus.OPTIMAL:
        assert bnb.objective_value == pytest.approx(cp.solution.objective_value, abs=1e-9)
    # CP-SAT never dresses an unproven incumbent as a proof.
    if cp.solution.status is not ScheduleRunStatus.OPTIMAL:
        assert cp.solution.proven_optimal is False
        assert cp.solution.bound is None and cp.solution.gap is None


@_needs_cpsat
def test_cpsat_proves_infeasibility_for_a_mandate_that_cannot_fit() -> None:
    """Two mandated wheelchair riders, overlapping mandatory windows, one
    wheelchair position. CP-SAT must reach the same PROOF the branch-and-bound
    does -- INFEASIBLE, no plan accepted -- not a partial plan."""
    problem = DecisionProblem(
        tenant_id=new_id(TenantId),
        policy=_policy(),
        vehicles=(_vehicle(4, 1),),
        requests=(
            RideRequest(request_id=new_id(RequestId), pickup_window_start=_at(0), pickup_window_end=_at(5), dropoff_window_end=_at(60), needs_wheelchair=True, nominal_ride_time_minutes=40, max_ride_time_minutes=60, must_serve=True),
            RideRequest(request_id=new_id(RequestId), pickup_window_start=_at(0), pickup_window_end=_at(5), dropoff_window_end=_at(60), needs_wheelchair=True, nominal_ride_time_minutes=40, max_ride_time_minutes=60, must_serve=True),
        ),
    )
    cp = solve_cpsat(problem, seed=0)
    assert cp.status is ScheduleRunStatus.INFEASIBLE
    assert cp.assignments == ()
    assert cp.proven_optimal is False
    assert cp.objective_value is None and cp.bound is None and cp.gap is None
    assert solve(problem).status is ScheduleRunStatus.INFEASIBLE  # both agree


def _hard_instance(n_requests: int) -> DecisionProblem:
    """A contended instance CP-SAT cannot close on a small budget. Fixed seed and
    a DETERMINISTIC budget, so 'it timed out' is reproducible rather than a
    property of how busy this machine happened to be."""
    rng = random.Random(11)
    requests = []
    for _ in range(n_requests):
        start = rng.randint(0, 300)
        requests.append(
            RideRequest(
                request_id=new_id(RequestId), pickup_window_start=_at(start),
                pickup_window_end=_at(start + 90), dropoff_window_end=_at(start + 240),
                party_size=rng.randint(1, 3), nominal_ride_time_minutes=rng.randint(10, 60),
                max_ride_time_minutes=120, must_serve=False,
            )
        )
    return DecisionProblem(
        tenant_id=new_id(TenantId), policy=_policy(time_granularity_minutes=1),
        vehicles=(_vehicle(2, 0, 600), _vehicle(2, 0, 600), _vehicle(3, 0, 600)),
        requests=tuple(requests),
    )


@_needs_cpsat
def test_cpsat_timeout_with_an_incumbent_reports_timeout_and_moves_the_bound_off_the_solution() -> None:
    """CP-SAT finds a plan but cannot prove it optimal. The DecisionSolution must
    say TIMEOUT with NO bound and NO gap -- its documented contract -- while the
    genuine dual bound remains available on the outcome. This is the blueprint-15
    failure mode ('solver timeout returned as valid optimal plan') at the exact
    seam where a bound exists and would be tempting to attach."""
    problem = _hard_instance(60)
    out = solve_cpsat_detailed(problem, seed=0, max_deterministic_time=0.05)

    assert out.raw_status == "FEASIBLE"  # incumbent, no proof
    assert out.solution.status is ScheduleRunStatus.TIMEOUT
    assert out.solution.proven_optimal is False
    assert out.solution.bound is None and out.solution.gap is None
    # The bound is real and strictly below the incumbent -- a genuine open gap.
    assert out.bound is not None and out.objective is not None
    assert out.bound < out.objective
    assert out.gap > 0.0
    assert out.hit_limit is True
    assert is_feasible(problem, out.solution)
    assert out.solution.assignments  # it really did have an incumbent


@_needs_cpsat
def test_cpsat_timeout_with_no_incumbent_denies_everything_with_solver_timeout() -> None:
    """The other timeout shape: no solution found at all. Every request must be
    denied SOLVER_TIMEOUT, and no objective may be invented."""
    problem = _hard_instance(80)
    out = solve_cpsat_detailed(problem, seed=0, max_deterministic_time=0.05)

    assert out.raw_status == "UNKNOWN"
    assert out.solution.status is ScheduleRunStatus.TIMEOUT
    assert out.solution.assignments == ()
    assert out.solution.objective_value is None
    assert len(out.solution.unserved) == len(problem.requests)
    assert all(ReasonCode.SOLVER_TIMEOUT in d.reason_codes for d in out.solution.unserved)
    assert out.bound is not None  # a bound exists even with no incumbent


# --- 3. the portfolio is stronger than its parts --------------------------

@_needs_cpsat
def test_portfolio_returns_a_proof_where_the_branch_and_bound_only_timed_out() -> None:
    """This is the whole justification for a portfolio. The hand-rolled search
    exhausts its node budget and can only say TIMEOUT; CP-SAT proves the optimum;
    the portfolio must return the PROOF, and must say so."""
    problem = _budget_starved_problem()
    solution, report = solve_portfolio(problem, seed=3)

    assert report.run("exact-bnb").status == "timeout"
    assert report.winner == "cpsat"
    assert solution.status is ScheduleRunStatus.OPTIMAL
    assert solution.proven_optimal is True
    assert solution.solver_name == CPSAT_SOLVER_NAME
    assert "PROVED" in report.winner_reason
    assert report.best_bound == solution.objective_value
    assert report.portfolio_gap == pytest.approx(0.0)
    assert is_feasible(problem, solution)


def test_report_accounts_for_every_strategy_and_never_drops_one() -> None:
    problem = _budget_starved_problem()
    _solution, report = solve_portfolio(problem, seed=3)
    assert {r.name for r in report.runs} == {"exact-bnb", "greedy", "cpsat"}
    for run in report.runs:
        assert run.detail  # each carries a reason for what it did
        assert run.seed == 3


# --- 4. determinism --------------------------------------------------------

@_needs_cpsat
def test_same_seed_and_deterministic_budget_gives_an_identical_answer() -> None:
    """Determinism under a WORK budget, not a clock. Byte-identical solution and
    the same winner, twice."""
    problem = _budget_starved_problem()
    first_sol, first_rep = solve_portfolio(problem, seed=17)
    second_sol, second_rep = solve_portfolio(problem, seed=17)

    assert first_rep.deterministic is True
    assert first_sol.model_dump() == second_sol.model_dump()
    assert first_rep.winner == second_rep.winner
    assert first_rep.best_bound == second_rep.best_bound
    assert [r.status for r in first_rep.runs] == [r.status for r in second_rep.runs]
    assert [r.objective for r in first_rep.runs] == [r.objective for r in second_rep.runs]


@_needs_cpsat
@pytest.mark.parametrize("trial", range(12))
def test_property_portfolio_is_deterministic_across_random_instances(trial: int) -> None:
    problem = _random_instance(random.Random(500 + trial))
    a_sol, a_rep = solve_portfolio(problem, seed=trial)
    b_sol, b_rep = solve_portfolio(problem, seed=trial)
    assert a_sol.model_dump() == b_sol.model_dump()
    assert a_rep.winner == b_rep.winner


@_needs_cpsat
def test_a_wall_clock_cap_is_reported_as_non_deterministic() -> None:
    """The portfolio may be given a wall-clock escape hatch, but it must not then
    claim reproducibility. Determinism is a property of the BUDGET, and the
    report tells the truth about which budget was used."""
    problem = _budget_starved_problem()
    _sol, report = solve_portfolio(problem, seed=5, wall_cap_s=5.0)
    assert report.deterministic is False
    assert report.run("cpsat").deterministic is False
    # The strategies on work budgets are still individually deterministic.
    assert report.run("exact-bnb").deterministic is True


# --- 5. nothing wins without independent verification ---------------------

def test_an_infeasible_strategy_output_is_disqualified_not_returned(monkeypatch) -> None:
    """Break a strategy so it emits an assignment that violates the pickup
    window, and confirm the portfolio disqualifies it instead of returning it.
    The greedy backend is sabotaged at the seam the portfolio calls."""
    from packages.decide.ir import Assignment, DecisionSolution

    def _sabotaged(problem, seed):
        req = problem.requests[0]
        return DecisionSolution(
            status=ScheduleRunStatus.FEASIBLE,
            assignments=(
                Assignment(
                    request_id=req.request_id,
                    vehicle_id=problem.vehicles[0].vehicle_id,
                    # Far outside the pickup window -- a real hard-constraint breach.
                    pickup_time=_at(10_000),
                    dropoff_time=_at(10_020),
                ),
            ),
            unserved=(), objective_value=-1.0, bound=None, gap=None, seed=seed,
            solver_name="sabotaged", solver_version="0",
        )

    monkeypatch.setattr("packages.decide.portfolio._solve_greedy", _sabotaged)
    problem = _budget_starved_problem()
    solution, report = solve_portfolio(problem, seed=2)

    greedy = report.run("greedy")
    assert greedy.disqualified is True and greedy.verified is False
    assert "independent checker rejected it" in greedy.error
    # Its (impossibly good) objective of -1.0 did NOT win.
    assert report.winner != "greedy"
    assert solution.solver_name != "sabotaged"
    assert is_feasible(problem, solution)


# --- 6. provers may not contradict each other -----------------------------

def test_two_disagreeing_proofs_raise_rather_than_being_tie_broken() -> None:
    """Hand-built: two solutions both claiming a proven optimum, with different
    objectives. The dispatcher must refuse to choose."""
    from packages.decide.ir import DecisionSolution

    def _proof(objective: float, name: str) -> DecisionSolution:
        return DecisionSolution(
            status=ScheduleRunStatus.OPTIMAL, assignments=(), unserved=(),
            objective_value=objective, bound=objective, gap=0.0, seed=0,
            solver_name=name, solver_version="0",
        )

    with pytest.raises(PortfolioContradiction, match="proved optimum"):
        _assert_no_decision_contradiction([("a", _proof(40.0, "a")), ("b", _proof(38.0, "b"))])


def test_a_proof_of_optimality_against_a_proof_of_infeasibility_raises() -> None:
    from packages.decide.ir import DecisionSolution

    optimal = DecisionSolution(
        status=ScheduleRunStatus.OPTIMAL, assignments=(), unserved=(), objective_value=40.0,
        bound=40.0, gap=0.0, seed=0, solver_name="a", solver_version="0",
    )
    infeasible = DecisionSolution(
        status=ScheduleRunStatus.INFEASIBLE, assignments=(), unserved=(), objective_value=None,
        bound=None, gap=None, seed=0, solver_name="b", solver_version="0",
    )
    with pytest.raises(PortfolioContradiction, match="INFEASIBLE"):
        _assert_no_decision_contradiction([("a", optimal), ("b", infeasible)])


def test_agreeing_proofs_do_not_raise() -> None:
    """The positive control for the two tests above: identical proofs must pass,
    or the contradiction check would be trivially satisfied by always raising."""
    from packages.decide.ir import DecisionSolution

    def _proof(name: str) -> DecisionSolution:
        return DecisionSolution(
            status=ScheduleRunStatus.OPTIMAL, assignments=(), unserved=(), objective_value=40.0,
            bound=40.0, gap=0.0, seed=0, solver_name=name, solver_version="0",
        )

    _assert_no_decision_contradiction([("a", _proof("a")), ("b", _proof("b"))])


# --- portfolio-wide invariants over random instances ----------------------

@_needs_cpsat
@pytest.mark.parametrize("trial", range(25))
def test_property_portfolio_answer_is_always_feasible_and_never_overclaims(trial: int) -> None:
    problem = _random_instance(random.Random(900 + trial))
    solution, report = solve_portfolio(problem, seed=trial)

    assert is_feasible(problem, solution)
    assert report.winner is not None
    assert report.run(report.winner).verified is True
    if solution.status is ScheduleRunStatus.OPTIMAL:
        assert solution.gap == 0.0 and solution.bound is not None
        served = {str(a.request_id) for a in solution.assignments}
        assert all(str(r.request_id) in served for r in problem.requests if r.must_serve)
    else:
        assert solution.proven_optimal is False
