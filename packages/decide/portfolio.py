"""Solver portfolio and dispatcher (Program F, v0.3).

`packages.decide.solver` recorded "CP-SAT / MILP / SMT / a portfolio" as an
aspiration. This module is the portfolio half: instead of one solver whose
weaknesses are the product's weaknesses, several strategies run on the same
problem and the dispatcher returns the best answer ANY of them produced, with a
report saying which one produced it and why it won.

The report is the point. A portfolio that silently returns "an answer" is worse
than a single solver, because it hides which technique is actually carrying the
product. `PortfolioReport` therefore records, per strategy: whether it was even
available on this machine, whether it ran, what it returned, its objective, its
dual bound, its gap, its seed, its wall time, and whether its budget was
deterministic. Nothing is dropped -- an unavailable strategy appears as
unavailable-with-a-reason, never as absent.

FOUR PROPERTIES THIS DISPATCHER HOLDS.

1. INDEPENDENT VERIFICATION BEFORE ELIGIBILITY. A strategy's output is passed to
   the independent checker (`packages.decide.feasibility`) BEFORE it is allowed
   to compete. A strategy that returns an infeasible answer is disqualified and
   recorded as such; it cannot win by being cheap and wrong. The portfolio never
   trusts a solver's self-report.

2. CONTRADICTION IS AN ERROR, NOT A TIE-BREAK. Two strategies that both claim a
   proof cannot disagree. If one proves an optimum of 40 and another proves 38,
   or one proves optimality while another proves infeasibility, or a heuristic's
   verified incumbent falls BELOW another strategy's rigorous lower bound, then
   one of them is wrong and the portfolio raises `PortfolioContradiction` rather
   than picking a winner. Running several solvers on one problem buys this
   cross-check; quietly discarding it would waste the only free correctness
   evidence a portfolio produces.

3. DETERMINISTIC SELECTION. The winner is chosen by a total order over
   (proof strength, objective, strategy name) -- never by which finished first.
   Wall-clock racing would make the returned answer depend on machine load,
   which is the standard way a portfolio becomes irreproducible.

4. HONEST DETERMINISM ACCOUNTING. Every strategy is given a DETERMINISTIC budget
   by default: CP-SAT gets `max_deterministic_time` (not seconds), the LNS gets
   an iteration count (not a time limit), the branch-and-bound gets its node
   budget. Under those budgets the same problem and seed give the same answer on
   any machine. `wall_cap_s` is an opt-in safety valve; if it engages, the run is
   marked `deterministic=False` and the report says so. The portfolio never
   claims reproducibility it did not buy.

The portfolio-level product is a bounded claim: the best verified incumbent
across strategies, and the best rigorous lower bound across strategies, hence a
gap the platform computed for itself rather than borrowed from a paper.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from packages.canonical.vocab import ScheduleRunStatus
from packages.decide.capability import ortools_capability
from packages.decide.darp_ir import DarpInstance, DarpSolution
from packages.decide.feasibility import (
    check_darp_feasibility,
    check_feasibility,
    darp_objective,
)
from packages.decide.ir import DecisionProblem, DecisionSolution
from packages.decide.solver import _solve_exact, _solve_greedy

PORTFOLIO_VERSION = "0.3.0"

_GAP_TOLERANCE = 1e-6  # float noise only; never a slack that hides a real contradiction


class PortfolioContradiction(AssertionError):
    """Two strategies produced mutually impossible claims about one problem.

    This is always a bug in a solver (or in the checker), never a condition to
    recover from, so it is raised rather than reported. See property 2 above.
    """


@dataclass(frozen=True)
class StrategyRun:
    """What one strategy did. Complete by construction -- a strategy that was
    unavailable, errored, or was disqualified still gets a record."""

    name: str
    available: bool
    ran: bool
    status: str
    objective: float | None
    bound: float | None
    gap: float | None
    seed: int
    wall_time_s: float
    deterministic: bool
    detail: str
    verified: bool = False
    disqualified: bool = False
    error: str | None = None

    def to_record(self) -> dict:
        return {
            "strategy": self.name,
            "available": self.available,
            "ran": self.ran,
            "status": self.status,
            "objective": self.objective,
            "bound": self.bound,
            "gap": self.gap,
            "seed": self.seed,
            "wall_time_s": self.wall_time_s,
            "deterministic": self.deterministic,
            "verified_by_independent_checker": self.verified,
            "disqualified": self.disqualified,
            "detail": self.detail,
            "error": self.error,
        }


@dataclass(frozen=True)
class PortfolioReport:
    """Which strategy won, on what evidence, and what every other one did."""

    problem_key: str
    seed: int
    runs: tuple[StrategyRun, ...]
    winner: str | None
    winner_reason: str
    best_bound: float | None
    portfolio_gap: float | None
    deterministic: bool
    wall_time_s: float
    portfolio_version: str = PORTFOLIO_VERSION

    def run(self, name: str) -> StrategyRun | None:
        return next((r for r in self.runs if r.name == name), None)

    @property
    def strategies_available(self) -> tuple[str, ...]:
        return tuple(r.name for r in self.runs if r.available)

    @property
    def strategies_unavailable(self) -> tuple[str, ...]:
        return tuple(r.name for r in self.runs if not r.available)

    def to_record(self) -> dict:
        return {
            "problem_key": self.problem_key,
            "seed": self.seed,
            "winner": self.winner,
            "winner_reason": self.winner_reason,
            "best_bound": self.best_bound,
            "portfolio_gap": self.portfolio_gap,
            "deterministic": self.deterministic,
            "wall_time_s": self.wall_time_s,
            "portfolio_version": self.portfolio_version,
            "runs": [r.to_record() for r in self.runs],
        }


# ==========================================================================
# Portfolio over the v0.1 Decision IR (assignment problems).
# ==========================================================================

_DECISION_STRATEGIES = ("exact-bnb", "greedy", "cpsat")


def solve_portfolio(
    problem: DecisionProblem,
    *,
    seed: int = 0,
    strategies: tuple[str, ...] = _DECISION_STRATEGIES,
    cpsat_deterministic_time: float = 30.0,
    wall_cap_s: float | None = None,
) -> tuple[DecisionSolution, PortfolioReport]:
    """Run every available strategy on `problem` and return the best VERIFIED
    answer plus the report explaining the choice.

    Deterministic when `wall_cap_s` is None (the default): each strategy runs
    under a work budget, not a clock, so the same problem and seed give the same
    answer regardless of machine speed.
    """
    t0 = time.perf_counter()
    runs: list[StrategyRun] = []
    candidates: list[tuple[str, DecisionSolution]] = []

    for name in strategies:
        run, solution = _run_decision_strategy(
            name, problem, seed, cpsat_deterministic_time, wall_cap_s
        )
        runs.append(run)
        if solution is not None and not run.disqualified:
            candidates.append((name, solution))

    _assert_no_decision_contradiction(candidates)
    winner, solution, reason = _select_decision_winner(candidates, runs)
    best_bound = _best_bound(runs)
    wall = time.perf_counter() - t0

    report = PortfolioReport(
        problem_key=f"decision:{len(problem.requests)}req/{len(problem.vehicles)}veh",
        seed=seed,
        runs=tuple(runs),
        winner=winner,
        winner_reason=reason,
        best_bound=best_bound,
        portfolio_gap=_gap(solution.objective_value if solution else None, best_bound),
        deterministic=all(r.deterministic for r in runs if r.ran),
        wall_time_s=round(wall, 4),
    )
    if solution is None:
        raise RuntimeError(f"no strategy produced a usable answer: {report.to_record()}")
    return solution, report


def _run_decision_strategy(
    name: str, problem: DecisionProblem, seed: int, cpsat_dt: float, wall_cap_s: float | None
) -> tuple[StrategyRun, DecisionSolution | None]:
    if name == "cpsat":
        cap = ortools_capability()
        if not cap.available:
            return (
                StrategyRun(
                    name=name, available=False, ran=False, status="unavailable",
                    objective=None, bound=None, gap=None, seed=seed, wall_time_s=0.0,
                    deterministic=True, detail=cap.detail,
                ),
                None,
            )

    t0 = time.perf_counter()
    bound: float | None = None
    gap: float | None = None
    try:
        if name == "exact-bnb":
            solution = _solve_exact(problem, seed)
            if solution.status is ScheduleRunStatus.OPTIMAL:
                bound, gap = solution.objective_value, 0.0
            detail = f"branch-and-bound, node budget {problem.policy.max_search_nodes}"
        elif name == "greedy":
            solution = _solve_greedy(problem, seed)
            detail = "cheapest-first greedy insertion; proves nothing by design"
        elif name == "cpsat":
            from packages.decide.cpsat import solve_cpsat_detailed

            outcome = solve_cpsat_detailed(
                problem,
                seed=seed,
                max_deterministic_time=cpsat_dt,
                max_time_s=wall_cap_s,
            )
            solution = outcome.solution
            bound, gap = outcome.bound, outcome.gap
            detail = (
                f"CP-SAT {outcome.raw_status}, deterministic budget {cpsat_dt} "
                f"(used {outcome.deterministic_time})"
            )
        else:
            raise ValueError(f"unknown decision strategy {name!r}")
    except Exception as exc:
        return (
            StrategyRun(
                name=name, available=True, ran=True, status="error", objective=None,
                bound=None, gap=None, seed=seed,
                wall_time_s=round(time.perf_counter() - t0, 4),
                deterministic=wall_cap_s is None, detail="raised during solve",
                error=f"{type(exc).__name__}: {exc}",
            ),
            None,
        )

    wall = round(time.perf_counter() - t0, 4)
    # PROPERTY 1: verify independently before this answer may compete.
    violations = check_feasibility(problem, solution)
    verified = not violations
    return (
        StrategyRun(
            name=name, available=True, ran=True, status=solution.status.value,
            objective=solution.objective_value, bound=bound, gap=gap, seed=seed,
            wall_time_s=wall,
            deterministic=(wall_cap_s is None) if name == "cpsat" else True,
            detail=detail, verified=verified, disqualified=not verified,
            error=None if verified else f"independent checker rejected it: {violations[:3]}",
        ),
        solution,
    )


def _assert_no_decision_contradiction(candidates) -> None:
    """PROPERTY 2. Provers may not disagree with each other."""
    proofs = [(n, s) for n, s in candidates if s.proven_optimal]
    infeasible = [n for n, s in candidates if s.status is ScheduleRunStatus.INFEASIBLE]
    if proofs and infeasible:
        raise PortfolioContradiction(
            f"{proofs[0][0]} proved an optimum of {proofs[0][1].objective_value} while "
            f"{infeasible[0]} proved the same problem INFEASIBLE"
        )
    for (na, sa), (nb, sb) in zip(proofs, proofs[1:]):
        if abs((sa.objective_value or 0.0) - (sb.objective_value or 0.0)) > _GAP_TOLERANCE:
            raise PortfolioContradiction(
                f"{na} proved optimum {sa.objective_value} but {nb} proved "
                f"{sb.objective_value} on the same problem"
            )


def _decision_rank(name: str, solution: DecisionSolution) -> tuple:
    """PROPERTY 3: a total order, evaluated on results only -- never on speed."""
    proof = 0 if solution.proven_optimal else 1
    objective = solution.objective_value if solution.objective_value is not None else math.inf
    return (proof, objective, name)


def _select_decision_winner(candidates, runs) -> tuple[str | None, DecisionSolution | None, str]:
    if not candidates:
        return None, None, "no strategy produced a verified answer"
    # A proven INFEASIBLE is a proof about the problem, not a plan to compare.
    for name, sol in sorted(candidates, key=lambda c: c[0]):
        if sol.status is ScheduleRunStatus.INFEASIBLE:
            return name, sol, (
                f"{name} PROVED no schedule serves every mandated request; a proof of "
                f"infeasibility outranks any partial plan"
            )
    name, solution = min(candidates, key=lambda c: _decision_rank(c[0], c[1]))
    others = [
        f"{r.name}={r.status}" for r in runs if r.name != name and r.ran and not r.disqualified
    ]
    if solution.proven_optimal:
        why = f"{name} PROVED optimality at objective {solution.objective_value} (gap 0)"
    else:
        why = (
            f"{name} produced the best verified objective {solution.objective_value} "
            f"with status {solution.status.value}; no strategy proved optimality"
        )
    if others:
        why += f". Others: {', '.join(others)}"
    return name, solution, why


# ==========================================================================
# Portfolio over the DARP routing IR.
# ==========================================================================

_DARP_STRATEGIES = ("regret-construction", "lns", "cpsat-darp")


def solve_darp_portfolio(
    instance: DarpInstance,
    *,
    seed: int = 0,
    strategies: tuple[str, ...] = _DARP_STRATEGIES,
    lns_iterations: int = 600,
    cpsat_deterministic_time: float = 30.0,
    wall_cap_s: float | None = None,
) -> tuple[DarpSolution | None, PortfolioReport]:
    """Run every available routing strategy on `instance`.

    The two families contribute different things and the report keeps them
    distinct: the heuristics contribute PRIMAL quality (a good route), CP-SAT
    contributes a rigorous DUAL bound. `portfolio_gap` is the gap between the
    best verified route and the best bound -- a self-computed optimality gap that
    borrows nothing from a published table.
    """
    t0 = time.perf_counter()
    runs: list[StrategyRun] = []
    candidates: list[tuple[str, DarpSolution]] = []
    bounds: list[tuple[str, float]] = []

    for name in strategies:
        run, solution, bound = _run_darp_strategy(
            name, instance, seed, lns_iterations, cpsat_deterministic_time, wall_cap_s
        )
        runs.append(run)
        if solution is not None and not run.disqualified:
            candidates.append((name, solution))
        if bound is not None:
            bounds.append((name, bound))

    _assert_no_darp_contradiction(instance, candidates, bounds)
    winner, solution, reason = _select_darp_winner(candidates, runs, bounds)
    best_bound = max((b for _n, b in bounds), default=None)
    incumbent = darp_objective(instance, solution) if solution is not None and solution.status == "feasible" else None
    wall = time.perf_counter() - t0

    return solution, PortfolioReport(
        problem_key=f"darp:{instance.name}",
        seed=seed,
        runs=tuple(runs),
        winner=winner,
        winner_reason=reason,
        best_bound=best_bound,
        portfolio_gap=_gap(incumbent, best_bound),
        deterministic=all(r.deterministic for r in runs if r.ran),
        wall_time_s=round(wall, 3),
    )


def _run_darp_strategy(
    name, instance, seed, lns_iterations, cpsat_dt, wall_cap_s
) -> tuple[StrategyRun, DarpSolution | None, float | None]:
    if name == "cpsat-darp":
        cap = ortools_capability()
        if not cap.available:
            return (
                StrategyRun(
                    name=name, available=False, ran=False, status="unavailable",
                    objective=None, bound=None, gap=None, seed=seed, wall_time_s=0.0,
                    deterministic=True, detail=cap.detail,
                ),
                None,
                None,
            )

    from packages.decide.darp_solver import solve_darp

    t0 = time.perf_counter()
    bound: float | None = None
    gap: float | None = None
    try:
        if name == "regret-construction":
            solution = solve_darp(instance, seed=seed, max_iterations=0, time_limit_s=None)
            detail = "regret-2 insertion only, no improvement phase"
        elif name == "lns":
            solution = solve_darp(
                instance, seed=seed, max_iterations=lns_iterations, time_limit_s=wall_cap_s
            )
            detail = f"ruin-and-recreate LNS, {lns_iterations} iterations"
        elif name == "cpsat-darp":
            from packages.decide.cpsat_darp import solve_darp_cpsat

            outcome = solve_darp_cpsat(
                instance, seed=seed, max_deterministic_time=cpsat_dt, max_time_s=wall_cap_s
            )
            solution = outcome.solution
            bound = outcome.lower_bound
            gap = _gap(outcome.objective, bound)
            detail = (
                f"CP-SAT {outcome.raw_status} on a lattice relaxation (scale {outcome.scale}); "
                f"{outcome.detail}"
            )
            if solution is None:
                return (
                    StrategyRun(
                        name=name, available=True, ran=True, status="bound-only",
                        objective=None, bound=bound, gap=None, seed=seed,
                        wall_time_s=round(time.perf_counter() - t0, 3),
                        deterministic=wall_cap_s is None, detail=detail,
                    ),
                    None,
                    bound,
                )
        else:
            raise ValueError(f"unknown DARP strategy {name!r}")
    except Exception as exc:
        return (
            StrategyRun(
                name=name, available=True, ran=True, status="error", objective=None,
                bound=None, gap=None, seed=seed,
                wall_time_s=round(time.perf_counter() - t0, 3),
                deterministic=wall_cap_s is None, detail="raised during solve",
                error=f"{type(exc).__name__}: {exc}",
            ),
            None,
            None,
        )

    wall = round(time.perf_counter() - t0, 3)
    # PROPERTY 1: independent verification before eligibility.
    violations = check_darp_feasibility(instance, solution)
    verified = not violations
    objective = darp_objective(instance, solution) if solution.status == "feasible" else None
    deterministic = True if name == "regret-construction" else wall_cap_s is None
    return (
        StrategyRun(
            name=name, available=True, ran=True, status=solution.status,
            objective=objective, bound=bound, gap=gap, seed=seed, wall_time_s=wall,
            deterministic=deterministic, detail=detail, verified=verified,
            disqualified=not verified,
            error=None if verified else f"independent checker rejected it: {violations[:3]}",
        ),
        solution,
        bound,
    )


def _assert_no_darp_contradiction(instance, candidates, bounds) -> None:
    """PROPERTY 2 for routing: a verified route cannot be cheaper than a rigorous
    lower bound. If it is, either the bound's relaxation argument is broken or
    the checker accepted something it should not have -- both are bugs."""
    if not bounds:
        return
    best = max(b for _n, b in bounds)
    holder = max(bounds, key=lambda nb: nb[1])[0]
    for name, sol in candidates:
        if sol.status != "feasible":
            continue
        obj = darp_objective(instance, sol)
        if obj < best - _darp_bound_tolerance(instance):
            raise PortfolioContradiction(
                f"{name} produced a checker-verified routing of {obj} on {instance.name}, "
                f"below {holder}'s rigorous lower bound of {best}"
            )


def _darp_bound_tolerance(instance: DarpInstance) -> float:
    """Slack for the lattice discretization only (see cpsat_darp.lattice_tolerance),
    plus float noise. Deliberately tiny: a real contradiction must not fit inside it."""
    from packages.decide.cpsat_darp import _SCALE

    return (2 * instance.num_requests + instance.num_vehicles) / _SCALE + _GAP_TOLERANCE


def _select_darp_winner(candidates, runs, bounds):
    if not candidates:
        bound_names = ", ".join(f"{n}={b}" for n, b in bounds)
        return None, None, (
            "no strategy produced a checker-verified routing"
            + (f"; bounds only from {bound_names}" if bounds else "")
        )
    # Full service first, then cheaper, then name. Never by wall time.
    def rank(item):
        name, sol = item
        complete = 0 if sol.status == "feasible" else 1
        objective = sol.objective if sol.objective is not None else math.inf
        return (complete, objective, name)

    name, solution = min(candidates, key=rank)
    others = [f"{r.name}={r.status}" for r in runs if r.name != name and r.ran]
    why = (
        f"{name} produced the best checker-verified routing "
        f"(objective {solution.objective}, {len(solution.served_requests)}/"
        f"{solution.num_requests} served)"
    )
    if bounds:
        best = max(b for _n, b in bounds)
        holder = max(bounds, key=lambda nb: nb[1])[0]
        why += f"; best rigorous lower bound {best} from {holder}"
    if others:
        why += f". Others: {', '.join(others)}"
    return name, solution, why


# --- shared helpers -------------------------------------------------------

def _best_bound(runs) -> float | None:
    vals = [r.bound for r in runs if r.bound is not None and not r.disqualified]
    return max(vals) if vals else None


def _gap(incumbent: float | None, bound: float | None) -> float | None:
    """Relative gap between an incumbent and a lower bound, or None when one
    cannot honestly be stated. None means "no gap", never zero.

    A non-positive bound returns None rather than a ratio. Early in a search
    CP-SAT's dual bound can be negative or zero; dividing by it yields a number
    that looks like a percentage and means nothing, which is worse than an
    absent value because a reader will believe it."""
    if incumbent is None or bound is None or bound <= 0.0:
        return None
    return (incumbent - bound) / bound
