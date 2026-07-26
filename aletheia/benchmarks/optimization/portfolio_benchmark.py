"""Solver-portfolio benchmark against the Cordeau dial-a-ride instances.

Runs `metis.decide.portfolio.solve_darp_portfolio` -- every available
strategy: regret construction, large-neighbourhood search, and the CP-SAT
lattice model -- over the published Cordeau type-a instances acquired through
the estate pipeline, and records which strategy won each one and why.

WHAT IS NEW HERE versus `aletheia/benchmarks/quality/darp_benchmark.py` (which is left
untouched and still measures the heuristic alone): this harness reports a
SELF-COMPUTED optimality gap. The heuristic benchmark can only state a gap
against a number transcribed from Cordeau (2006); if that transcription were
wrong, or the distance convention subtly different, the gap would be wrong and
nothing in the repository would notice. The portfolio's CP-SAT strategy produces
its own rigorous lower bound on each instance, so this harness reports:

  - `gap_to_our_bound_pct`   -- our incumbent vs OUR OWN proven lower bound.
                               Borrows nothing. This is the honest headline.
  - `gap_to_published_pct`   -- our incumbent vs the published value, for
                               comparability with the literature.
  - `bound_vs_published_pct` -- our bound vs the published optimum. A negative or
                               zero value is expected (a bound sits at or below
                               an optimum); a POSITIVE value on a proven-optimal
                               instance would mean our model contradicts the
                               literature, and is flagged as a defect.

Integrity, unchanged from the sibling harness and non-negotiable:

  - Every reported routing is validated by the routing-aware
    `check_darp_feasibility` AND, via `metis.decide.darp_bridge`, by the
    original v0.1 `check_feasibility`. A routing failing either is not counted.
  - The objective is recomputed independently from the routes; the solver's
    self-reported number is never used for a gap.
  - The portfolio itself raises on any contradiction between a verified route and
    a rigorous bound, so a silent inconsistency cannot reach this file.

STATUS. The Cordeau instances are SYNTHETIC academic benchmarks. Everything here
supports ALGORITHMIC claims only -- "this solver finds routings within X% of a
proven bound on published instances". Nothing here is evidence about any real
operator's service, riders, or costs, and no result in this file may be cited as
operational validation.

Usage:
    py -3 aletheia/benchmarks/optimization/portfolio_benchmark.py
        [--instances published|all|a2-16,a3-18] [--seed N]
        [--cpsat-time S] [--max-requests N] [--quick]

If the benchmark archive was never acquired, the harness says how to acquire it
and exits 0 -- nothing to benchmark is not a failure.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from metis.decide.capability import ortools_capability  # noqa: E402
from metis.decide.darp_bridge import project_darp_solution  # noqa: E402
from metis.decide.darp_loader import (  # noqa: E402
    find_benchmark_archive,
    list_zip_instances,
    load_zip_instance,
)
from metis.decide.feasibility import (  # noqa: E402
    check_darp_feasibility,
    check_feasibility,
    darp_objective,
)
from metis.decide.portfolio import PORTFOLIO_VERSION, solve_darp_portfolio  # noqa: E402

_HERE = Path(__file__).resolve().parent
_RESULTS = _HERE / "portfolio_results.json"
_SUMMARY = _HERE / "portfolio_summary.md"
# Read-only: the published reference values live with the heuristic benchmark
# that first cited them. Duplicating them here would create a second place for
# the same fact to drift.
_BEST_KNOWN = _REPO_ROOT / "aletheia" / "benchmarks" / "quality" / "best_known.json"


# The published Cordeau values are printed to two decimal places, so the true
# optimum sits within half a unit of the last place shown.
_PUBLISHED_ROUNDING = 0.005


def _lattice_tolerance(inst) -> float:
    """The most our CP-SAT bound can understate the true optimum -- see
    `metis.decide.cpsat_darp`. Tiny (~1e-5), but included so the defect test
    is expressed in terms of the actual claim rather than a round number."""
    from metis.decide.cpsat_darp import _SCALE

    return (2 * inst.num_requests + inst.num_vehicles) / _SCALE


def _lns_iterations(n: int, quick: bool) -> int:
    """LNS iteration budget, tapered hard with instance size.

    The taper is not tuning taste, it is a measured constraint. The LNS is pure
    Python and validates every candidate insertion position with a full route
    schedule, so its per-iteration cost grows steeply with ROUTE length -- which
    is 2n/K, not n. Measured here: a2-16 (16 nodes per route) ran 400 iterations
    in ~170s; a2-20 (20 nodes per route) had not finished 400 iterations after
    twenty minutes. A flat budget therefore does not terminate on the larger
    instances.

    These budgets are deliberately SMALL, and the consequence is stated rather
    than hidden: the heuristic's objective in this benchmark is its answer AT
    THIS BUDGET, not its best possible answer, and it would improve with more.
    The budget used is recorded per instance in the results JSON."""
    if quick:
        return 40
    if n <= 16:
        return 200
    if n <= 20:
        return 100
    if n <= 24:
        return 60
    if n <= 36:
        return 40
    return 25


def _cpsat_budget(n: int, base: float, quick: bool) -> float:
    """Deterministic-time budget, tapered for larger instances where CP-SAT will
    not close the model anyway and is only contributing a bound."""
    if quick:
        return min(base, 5.0)
    if n <= 24:
        return base
    if n <= 48:
        return base * 0.6
    return base * 0.35


def _run_instance(archive, name, best_known, seed, cpsat_time, quick) -> dict:
    inst = load_zip_instance(archive, name)
    n = inst.num_requests
    iterations = _lns_iterations(n, quick)
    budget = _cpsat_budget(n, cpsat_time, quick)

    t0 = time.perf_counter()
    solution, report = solve_darp_portfolio(
        inst, seed=seed, lns_iterations=iterations, cpsat_deterministic_time=budget
    )
    wall = time.perf_counter() - t0

    served = len(solution.served_requests) if solution is not None else 0
    fully_served = solution is not None and served == n

    # Two independent feasibility gates, as in the sibling harness.
    darp_violations = check_darp_feasibility(inst, solution) if solution is not None else []
    if solution is not None:
        problem, projected = project_darp_solution(inst, solution)
        v01_violations = check_feasibility(problem, projected)
    else:
        v01_violations = []
    both_pass = solution is not None and not darp_violations and not v01_violations

    objective = darp_objective(inst, solution) if (both_pass and fully_served) else None
    our_bound = report.best_bound

    ref = best_known.get(name)
    published = ref["best_known"] if ref else None
    published_is_optimal = bool(ref and ref["proven_optimal"])

    def pct(a, b):
        return None if (a is None or b is None or b == 0) else round((a - b) / b * 100.0, 4)

    gap_to_our_bound = pct(objective, our_bound)
    gap_to_published = pct(objective, published)
    bound_vs_published = pct(our_bound, published)
    # A lower bound above a PROVEN optimum would mean our model contradicts the
    # literature. Flagged loudly rather than averaged into a headline -- but the
    # threshold must respect the reference data's own precision. The published
    # values are printed to two decimal places, so the true optimum lies within
    # half a unit of the last place; a bound inside that band is agreement, not a
    # defect. An earlier, tighter threshold reported a2-20 (we prove 344.834,
    # the table prints 344.83) as a contradiction, which was a false alarm in a
    # file whose whole job is to be trustworthy.
    bound_defect = bool(
        published_is_optimal and our_bound is not None and published is not None
        and our_bound > published + _PUBLISHED_ROUNDING + _lattice_tolerance(inst)
    )

    return {
        "instance": name,
        "num_requests": n,
        "num_vehicles": inst.num_vehicles,
        "vehicle_capacity": inst.vehicle_capacity,
        "max_ride_time": inst.max_ride_time,
        "max_route_duration": inst.max_route_duration,
        "winner": report.winner,
        "winner_reason": report.winner_reason,
        "served": served,
        "fully_served": fully_served,
        "our_objective": round(objective, 4) if objective is not None else None,
        "our_lower_bound": round(our_bound, 4) if our_bound is not None else None,
        "gap_to_our_bound_pct": gap_to_our_bound,
        "published": published,
        "published_is_proven_optimal": published_is_optimal,
        "gap_to_published_pct": gap_to_published,
        "bound_vs_published_pct": bound_vs_published,
        "bound_above_published_optimum_DEFECT": bound_defect,
        "feasible": both_pass,
        "darp_checker_violations": len(darp_violations),
        "independent_v01_checker_violations": len(v01_violations),
        "deterministic": report.deterministic,
        "wall_time_s": round(wall, 3),
        "seed": seed,
        "lns_iterations": iterations,
        "cpsat_deterministic_budget": budget,
        "portfolio": report.to_record(),
    }


def _summary(meta: dict, results: list[dict]) -> str:
    counted = [r for r in results if r["gap_to_our_bound_pct"] is not None]
    pub_counted = [r for r in results if r["gap_to_published_pct"] is not None]
    wins: dict[str, int] = {}
    for r in results:
        if r["winner"]:
            wins[r["winner"]] = wins.get(r["winner"], 0) + 1
    defects = [r["instance"] for r in results if r["bound_above_published_optimum_DEFECT"]]

    lines = [
        "# Solver-portfolio benchmark -- honest results",
        f"_Generated {meta['generated_at']} by `aletheia/benchmarks/optimization/portfolio_benchmark.py`._",
        "",
        f"Portfolio v{meta['portfolio_version']}: `regret-construction`, `lns` (pure-Python "
        f"ruin-and-recreate), `cpsat-darp` (OR-Tools CP-SAT on a lattice relaxation). "
        f"OR-Tools: {meta['ortools']}. Seed {meta['seed']}. Python {meta['python']}.",
        "",
        "**Every counted routing passed BOTH independent feasibility checkers** (the routing-aware "
        "`check_darp_feasibility` and the original v0.1 `check_feasibility` via projection), and its "
        "objective was recomputed independently from the routes.",
        "",
        "## What the two gap columns mean",
        "- **gap vs our bound** -- our incumbent against a lower bound this repository PROVED for "
        "itself (CP-SAT on a relaxation whose rounding directions make the bound rigorous). "
        "Borrows nothing from the literature. This is the honest headline number.",
        "- **gap vs published** -- our incumbent against Cordeau (2006), for comparability only.",
        "",
        "## Headline",
    ]
    if counted:
        gaps = [r["gap_to_our_bound_pct"] for r in counted]
        lines += [
            f"- Instances with a self-computed gap: **{len(counted)}**.",
            f"- Median gap to our own proven bound: **{statistics.median(gaps):.2f}%**; "
            f"best {min(gaps):.2f}%, worst {max(gaps):.2f}%.",
        ]
    else:
        lines.append("- No instance produced both a verified routing and a bound.")
    if pub_counted:
        pgaps = [r["gap_to_published_pct"] for r in pub_counted]
        lines.append(
            f"- Median gap to the published value: **{statistics.median(pgaps):.2f}%**; "
            f"best {min(pgaps):.2f}%, worst {max(pgaps):.2f}%."
        )
    if wins:
        lines.append(
            "- Strategy that produced the returned routing: "
            + ", ".join(f"`{k}` x{v}" for k, v in sorted(wins.items()))
            + "."
        )
    bounded = [r for r in results if r["our_lower_bound"] is not None]
    lines.append(f"- Instances where CP-SAT contributed a rigorous lower bound: **{len(bounded)}/{len(results)}**.")
    unserved = [r["instance"] for r in results if not r["fully_served"]]
    if unserved:
        lines.append(f"- **Not fully served** (no gap counted): {', '.join(unserved)}.")
    if meta.get("excluded_for_runtime"):
        lines.append(
            f"- **NOT RUN** (excluded above {meta['max_requests_cap']} requests): "
            f"{', '.join(meta['excluded_for_runtime'])}. {meta['excluded_reason']}"
        )
    # Instances of the published set that this run simply did not cover. Stated
    # explicitly even when the selection was an explicit list, so a reader can
    # never mistake "not in the table" for "nothing to report".
    not_covered = [n for n in meta.get("published_set", []) if n not in {r["instance"] for r in results}]
    if not_covered:
        lines.append(
            f"- **NOT COVERED BY THIS RUN**: {', '.join(not_covered)}. No result was produced for "
            f"them here, so nothing in this file says anything about them either way."
        )
    if not meta.get("complete", True):
        lines.append(
            "- **THIS RUN IS INCOMPLETE.** It was interrupted before every requested instance "
            "finished; the rows below are real measurements, but the set is partial."
        )

    lines += ["", "## Integrity", ""]
    bad = [r["instance"] for r in results if not r["feasible"] and r["winner"]]
    lines.append(
        f"- Routings rejected by a checker: **{len(bad)}**" + (f" ({', '.join(bad)})" if bad else "")
        + "."
    )
    lines.append(
        f"- Bound-above-published-optimum defects: **{len(defects)}**"
        + (f" ({', '.join(defects)}) -- INVESTIGATE" if defects else " (none).")
    )
    lines.append(
        f"- All runs deterministic (work budgets, not wall clocks): "
        f"**{all(r['deterministic'] for r in results)}**."
    )

    lines += [
        "",
        "## Honest caveats",
        "",
        "- These are SYNTHETIC academic instances. They support algorithmic claims only. Nothing "
        "here is operational evidence, and no number in this file may be cited as validation "
        "against a real operator's service. Program F remains **Demonstrated**, not Validated.",
        "- CP-SAT solves a LATTICE RELAXATION of each instance (travel times floored, upper bounds "
        "loosened). That is what makes the bound rigorous, but it also means a routing CP-SAT "
        "considers optimal is not automatically feasible for the true instance -- each is "
        "re-scheduled in exact arithmetic and re-checked, and rejected if it fails.",
        "- `certified_optimal` means optimal WITHIN THE LATTICE RESOLUTION (a computed tolerance of "
        "(2n+K)/scale), not absolutely.",
        "- CP-SAT closes only the smallest instances. On larger ones its bound is weak and the gap "
        "reported against it overstates the true distance from optimality -- a weak bound makes us "
        "look worse than we are, which is the direction we prefer to be wrong in.",
        "- The heuristic budget is modest and single-seed. This is not a state-of-the-art DARP "
        "solver and no claim is made against any published solver.",
        "",
        "## Per-instance results",
        "",
        "| instance | n | K | winner | our obj | our bound | gap vs our bound | published | opt? | "
        "gap vs published | served | checkers | time (s) |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        def f(v, nd=2):
            return "-" if v is None else f"{v:.{nd}f}"
        lines.append(
            f"| {r['instance']} | {r['num_requests']} | {r['num_vehicles']} | "
            f"{r['winner'] or '-'} | {f(r['our_objective'])} | {f(r['our_lower_bound'])} | "
            f"{f(r['gap_to_our_bound_pct'])}% | {f(r['published'])} | "
            f"{'yes' if r['published_is_proven_optimal'] else ('no' if r['published'] else '-')} | "
            f"{f(r['gap_to_published_pct'])}% | {r['served']}/{r['num_requests']} | "
            f"{'PASS' if r['feasible'] else 'FAIL'} | {r['wall_time_s']:.1f} |"
        )
    return "\n".join(lines) + "\n"


def _partial_meta(args, cap, excluded, published_set, *, complete: bool) -> dict:
    """Run metadata. `complete` is False on the incremental writes made after each
    instance, so a file left behind by an interrupted run announces itself as
    partial rather than looking like a finished benchmark."""
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "complete": complete,
        "portfolio_version": PORTFOLIO_VERSION,
        "ortools": cap.detail,
        "python": sys.version.split()[0],
        "seed": args.seed,
        "quick": args.quick,
        "cpsat_deterministic_time_base": args.cpsat_time,
        "instance_selection": args.instances,
        "max_requests_cap": args.max_requests,
        "excluded_for_runtime": excluded,
        "published_set": published_set,
        "excluded_reason": (
            "The pure-Python LNS validates every candidate insertion position with a full "
            "route schedule, so its cost grows steeply with route length; these instances "
            "did not complete in a sensible benchmark window. They are NOT evidence of "
            "anything and are named here so their absence is visible."
        ) if excluded else None,
        "published_source": "Cordeau (2006), Operations Research 54(3); see "
                            "aletheia/benchmarks/quality/best_known.json for citation and per-value flags",
        "data_status": "SYNTHETIC academic benchmark instances -- algorithmic claims only, "
                       "never operational validation",
    }


def _write(meta: dict, results: list[dict]) -> None:
    _RESULTS.write_text(json.dumps({"meta": meta, "results": results}, indent=2) + "\n", encoding="utf-8")
    _SUMMARY.write_text(_summary(meta, results), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--instances", default="published",
                    help="'published' (those with a cited reference value), 'all', or a comma list")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--cpsat-time", type=float, default=45.0,
                    help="CP-SAT DETERMINISTIC-time budget per instance (not seconds)")
    ap.add_argument("--quick", action="store_true", help="small budgets, for a smoke run")
    ap.add_argument("--max-requests", type=int, default=0,
                    help="skip instances larger than this (0 = no cap). Skipped instances are "
                         "NAMED in the results and summary, never silently dropped.")
    args = ap.parse_args()

    archive = find_benchmark_archive()
    if archive is None:
        print("Cordeau DARP benchmark archive not acquired; nothing to benchmark.")
        print("Acquire it with the estate pipeline (data/acquired/catalog/cordeau-darp.manifest.json).")
        return 0

    best_known = json.loads(_BEST_KNOWN.read_text(encoding="utf-8"))["instances"]
    available = list_zip_instances(archive)
    published_set = [n for n in available if n in best_known]
    if args.instances == "published":
        names = [n for n in available if n in best_known]
    elif args.instances == "all":
        names = available
    else:
        names = [n.strip() for n in args.instances.split(",") if n.strip()]
    missing = [n for n in names if n not in available]
    if missing:
        print(f"unknown instances: {missing}", file=sys.stderr)
        return 2

    cap = ortools_capability()
    print(f"OR-Tools: {cap.detail}")

    excluded: list[str] = []
    if args.max_requests:
        kept = []
        for name in names:
            n = load_zip_instance(archive, name).num_requests
            (kept if n <= args.max_requests else excluded).append(name)
        names = kept
        if excluded:
            print(f"excluded for runtime (> {args.max_requests} requests): {', '.join(excluded)}")

    results = []
    for name in names:
        print(f"  {name} ...", flush=True)
        record = _run_instance(archive, name, best_known, args.seed, args.cpsat_time, args.quick)
        results.append(record)
        print(
            f"    winner={record['winner']} obj={record['our_objective']} "
            f"bound={record['our_lower_bound']} gap_vs_bound={record['gap_to_our_bound_pct']}% "
            f"gap_vs_published={record['gap_to_published_pct']}% ({record['wall_time_s']:.1f}s)",
            flush=True,
        )
        # Persist after EVERY instance. A run over the published set takes tens of
        # minutes; writing only at the end would mean an interrupted run produces
        # nothing at all, and the honest response to that is to lower the stakes
        # of an interruption rather than to hope there isn't one. `complete` says
        # whether every requested instance was reached.
        _write(_partial_meta(args, cap, excluded, published_set, complete=False), results)

    _write(_partial_meta(args, cap, excluded, published_set, complete=True), results)
    print(f"\nwrote {_RESULTS}\nwrote {_SUMMARY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
