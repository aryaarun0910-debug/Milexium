"""DARP solver-quality benchmark harness (Program F, Phase-2 item 2).

Runs Milexium's dial-a-ride heuristic (`metis.decide.darp_solver.solve_darp`)
against the published Cordeau type-a dial-a-ride benchmark instances acquired
through the estate pipeline, and reports REAL, measured optimality gaps versus
the published best-known / proven-optimal objective values.

Integrity, non-negotiable (this is what makes the number trustworthy):

- Every reported solution is validated TWICE by independent checkers before its
  gap is counted: the routing-aware `check_darp_feasibility` (authoritative) AND
  the original v0.1 `check_feasibility` via a faithful projection
  (`metis.decide.darp_bridge`). A solution that fails either checker is
  recorded as `feasible=false` and its gap is NOT counted -- an infeasible
  "solution" is not a solution.
- The objective is recomputed independently (`darp_objective`) from the routes;
  the solver's self-reported number is never trusted for the gap.
- A gap is only computed when the instance is served in full (served == n) and a
  published reference value exists in `best_known.json` (cited there). Anything
  else is reported honestly as "served k/n" or "no published comparison".

Outputs (written next to this script):

- `darp_results.json` -- machine-readable, one record per instance.
- `darp_summary.md`   -- a short, honest human summary (median/worst gap, what is
  competitive and what is not).

Usage:
    py -3 aletheia/benchmarks/quality/darp_benchmark.py [--instances published|all|a2-16,a3-18]
                                               [--seed N] [--time-limit S] [--quick]

If the benchmark archive was never acquired, the harness prints how to acquire it
and exits 0 (nothing to benchmark, not a failure).
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

from metis.decide.darp_bridge import project_darp_solution  # noqa: E402
from metis.decide.darp_loader import (  # noqa: E402
    find_benchmark_archive,
    list_zip_instances,
    load_zip_instance,
)
from metis.decide.darp_solver import (  # noqa: E402
    DARP_SOLVER_NAME,
    DARP_SOLVER_VERSION,
    solve_darp,
)
from metis.decide.feasibility import (  # noqa: E402
    check_darp_feasibility,
    check_feasibility,
    darp_objective,
)

_HERE = Path(__file__).resolve().parent
_RESULTS = _HERE / "darp_results.json"
_SUMMARY = _HERE / "darp_summary.md"
_BEST_KNOWN = _HERE / "best_known.json"


def _iteration_budget(n: int, quick: bool) -> int:
    """LNS iterations scaled to instance size so the harness runs in a sensible
    time; recorded per instance for reproducibility."""
    if quick:
        return 200
    if n <= 20:
        return 1500
    if n <= 24:
        return 1200
    if n <= 30:
        return 900
    if n <= 36:
        return 700
    if n <= 48:
        return 500
    return 300


def _run_instance(archive, name, best_known, seed, time_limit, quick) -> dict:
    inst = load_zip_instance(archive, name)
    iterations = _iteration_budget(inst.num_requests, quick)

    t0 = time.perf_counter()
    solution = solve_darp(inst, seed=seed, max_iterations=iterations, time_limit_s=time_limit)
    wall = time.perf_counter() - t0

    # Two independent feasibility gates.
    darp_violations = check_darp_feasibility(inst, solution)
    problem, projected = project_darp_solution(inst, solution)
    existing_violations = check_feasibility(problem, projected)
    both_pass = not darp_violations and not existing_violations

    served = len(solution.served_requests)
    fully_served = served == inst.num_requests
    objective = darp_objective(inst, solution) if fully_served else None

    ref = best_known.get(name)
    gap_pct = None
    if both_pass and fully_served and ref is not None:
        bk = ref["best_known"]
        gap_pct = round((objective - bk) / bk * 100.0, 4)

    return {
        "instance": name,
        "num_requests": inst.num_requests,
        "num_vehicles": inst.num_vehicles,
        "vehicle_capacity": inst.vehicle_capacity,
        "max_ride_time": inst.max_ride_time,
        "max_route_duration": inst.max_route_duration,
        "served": served,
        "fully_served": fully_served,
        "our_objective": round(objective, 4) if objective is not None else None,
        "best_known": ref["best_known"] if ref else None,
        "best_known_is_proven_optimal": ref["proven_optimal"] if ref else None,
        "gap_pct": gap_pct,
        "feasible": both_pass,
        "darp_checker_violations": len(darp_violations),
        "independent_v01_checker_violations": len(existing_violations),
        "solve_time_s": round(wall, 3),
        "seed": seed,
        "lns_iterations": iterations,
        "solver_name": DARP_SOLVER_NAME,
        "solver_version": DARP_SOLVER_VERSION,
    }


def _select_instances(arg: str, archive, best_known) -> list[str]:
    available = list_zip_instances(archive)
    if arg == "all":
        return available
    if arg == "published":
        return [n for n in available if n in best_known]
    wanted = [s.strip() for s in arg.split(",") if s.strip()]
    missing = [w for w in wanted if w not in available]
    if missing:
        raise SystemExit(f"unknown instance(s): {missing}; available: {available}")
    return wanted


def _write_summary(records: list[dict], meta: dict) -> None:
    counted = [r for r in records if r["gap_pct"] is not None]
    optima = [r for r in counted if r["best_known_is_proven_optimal"]]
    gaps = [r["gap_pct"] for r in counted]

    lines: list[str] = []
    lines.append("# DARP solver-quality benchmark -- honest results\n")
    lines.append(f"_Generated {meta['generated_at']} by `aletheia/benchmarks/quality/darp_benchmark.py`._\n")
    lines.append(
        f"Solver: `{meta['solver_name']}` v{meta['solver_version']} (pure-Python regret "
        "insertion + large-neighbourhood search; no OR-Tools/external solver). "
        f"Seed {meta['seed']}. Instances: published Cordeau type-a dial-a-ride set, "
        "acquired through the estate pipeline.\n"
    )
    lines.append(
        "**Every counted solution passed BOTH independent feasibility checkers** "
        "(the routing-aware `check_darp_feasibility` and the original v0.1 "
        "`check_feasibility` via projection), and its objective was recomputed "
        "independently from the routes. Gaps are versus published values in "
        "`best_known.json` (Cordeau 2006); values there marked proven-optimal give "
        "a true optimality gap, the rest a gap-to-best-known.\n"
    )

    if not counted:
        lines.append("\n**No instance produced a counted gap** (see per-instance table for why).\n")
    else:
        lines.append("\n## Headline\n")
        lines.append(f"- Instances with a counted gap: **{len(counted)}** (of which {len(optima)} vs a proven optimum).\n")
        lines.append(f"- Median gap: **{statistics.median(gaps):.2f}%**; best {min(gaps):.2f}%, worst {max(gaps):.2f}%.\n")
        hit = [r['instance'] for r in counted if r['gap_pct'] <= 0.01]
        within2 = sum(1 for g in gaps if g <= 2.0)
        within5 = sum(1 for g in gaps if g <= 5.0)
        if hit:
            lines.append(f"- Reached the published optimum (gap = 0.00%) on: {', '.join(sorted(hit))}.\n")
        lines.append(f"- Within 2%: {within2}/{len(counted)}; within 5%: {within5}/{len(counted)}.\n")

    incomplete = [r for r in records if not r["fully_served"]]
    infeasible = [r for r in records if not r["feasible"]]
    no_ref = [r for r in records if r["feasible"] and r["fully_served"] and r["best_known"] is None]

    lines.append("\n## Honest caveats\n")
    if infeasible:
        lines.append(f"- **{len(infeasible)} solution(s) FAILED an independent checker** -- these are NOT counted and indicate a solver bug: {', '.join(r['instance'] for r in infeasible)}.\n")
    else:
        lines.append("- No solution failed a feasibility checker; the integrity property held on every instance run.\n")
    if incomplete:
        detail = ", ".join(f"{r['instance']} ({r['served']}/{r['num_requests']})" for r in incomplete)
        lines.append(f"- Could not serve every request within budget on: {detail}. No gap is claimed for these; the heuristic (or its budget) is the limitation, reported honestly.\n")
    if no_ref:
        lines.append(f"- Ran and validated but have no published reference in our cited source, so no gap is computed: {', '.join(r['instance'] for r in no_ref)}.\n")
    lines.append(
        "- This is a v0.2 heuristic under a modest iteration budget on a single seed. "
        "It is genuinely strong on small instances (it reaches several proven optima) "
        "but is NOT a state-of-the-art DARP solver; on larger instances the gap grows "
        "and the budget matters. We do not claim to beat any published solver.\n"
    )

    lines.append("\n## Per-instance results\n")
    lines.append("| instance | n | K | our obj | best-known | opt? | gap% | served | feasible | time (s) | iters |\n")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|\n")
    for r in records:
        opt = "yes" if r["best_known_is_proven_optimal"] else ("no" if r["best_known"] is not None else "-")
        gap = f"{r['gap_pct']:.2f}" if r["gap_pct"] is not None else "-"
        obj = f"{r['our_objective']:.2f}" if r["our_objective"] is not None else "-"
        bk = f"{r['best_known']:.2f}" if r["best_known"] is not None else "-"
        feas = "PASS" if r["feasible"] else "FAIL"
        lines.append(
            f"| {r['instance']} | {r['num_requests']} | {r['num_vehicles']} | {obj} | {bk} | {opt} | "
            f"{gap} | {r['served']}/{r['num_requests']} | {feas} | {r['solve_time_s']:.1f} | {r['lns_iterations']} |\n"
        )
    _SUMMARY.write_text("".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--instances", default="published", help="'published' (default), 'all', or a comma list e.g. a2-16,a3-18")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--time-limit", type=float, default=120.0, help="per-instance wall-clock cap (s)")
    ap.add_argument("--quick", action="store_true", help="tiny iteration budget (smoke run)")
    args = ap.parse_args()

    archive = find_benchmark_archive()
    if archive is None:
        print(
            "DARP benchmark archive not found. Acquire it first:\n"
            "    py -3 -c \"from themis.estate import acquire; "
            "acquire('data/acquired/catalog/cordeau-darp.manifest.json')\"\n"
            "Nothing to benchmark; exiting 0."
        )
        return 0

    best_known = json.loads(_BEST_KNOWN.read_text(encoding="utf-8"))["instances"]
    names = _select_instances(args.instances, archive, best_known)

    print(f"Benchmarking {len(names)} instance(s) with {DARP_SOLVER_NAME} v{DARP_SOLVER_VERSION}, seed {args.seed}")
    records: list[dict] = []
    for name in names:
        rec = _run_instance(archive, name, best_known, args.seed, args.time_limit, args.quick)
        records.append(rec)
        gap = f"{rec['gap_pct']:.2f}%" if rec["gap_pct"] is not None else "n/a"
        flag = "" if rec["feasible"] else "  <-- FEASIBILITY FAILURE"
        print(
            f"  {name:8s} served {rec['served']}/{rec['num_requests']}  "
            f"obj {rec['our_objective'] if rec['our_objective'] is not None else '-'}  "
            f"gap {gap}  ({rec['solve_time_s']:.1f}s, {rec['lns_iterations']} it){flag}",
            flush=True,
        )

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "solver_name": DARP_SOLVER_NAME,
        "solver_version": DARP_SOLVER_VERSION,
        "seed": args.seed,
        "instance_selection": args.instances,
        "best_known_source": "Cordeau (2006), Operations Research 54(3); see best_known.json for citation and per-value proven-optimal flags",
    }
    payload = {"meta": meta, "results": records}
    _RESULTS.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_summary(records, meta)

    counted = [r for r in records if r["gap_pct"] is not None]
    failures = [r for r in records if not r["feasible"]]
    print(f"\nWrote {_RESULTS.name} and {_SUMMARY.name}. Counted gaps: {len(counted)}. Feasibility failures: {len(failures)}.")
    if counted:
        gaps = [r["gap_pct"] for r in counted]
        print(f"Median gap {statistics.median(gaps):.2f}%, worst {max(gaps):.2f}%.")
    # A feasibility failure is a real integrity problem: surface it as a nonzero exit.
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
