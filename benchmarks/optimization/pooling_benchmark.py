"""Pooling and future-capacity-value benchmark on the Cordeau dial-a-ride set.

WHAT QUESTION THIS ANSWERS. Not "is the score better" -- a better score that
changes no assignment is worthless. This harness asks whether pricing the FUTURE
at decision time changes the plan, and if so, who gains and who pays. Every
number below is a property of a plan that two independent checkers accepted.

FOUR PLANNERS, ONE METRIC CODE. All four are evaluated by
`packages.decide.pooling.evaluate_plan`, so a comparison across them is a
comparison of plans and not of reporting conventions:

  cheapest-insertion    online, irrevocable, cheapest certified insertion. The
                        rule `darp_solver._scan_insertions` already applies, so
                        it stands in for current practice inside this harness.
  capacity-aware        the same harness with ONE term added: the estimated
                        future trips a placement forecloses, accessible
                        foreclosure charged extra.
  lns                   `darp_solver.solve_darp`, the pre-existing heuristic.
  cpsat-darp            `cpsat_darp.solve_darp_cpsat`, the ADR-0060 exact model.

THE LAST TWO ARE OFFLINE AND SEE EVERY REQUEST BEFORE COMMITTING TO ANY. They are
the distance yardstick, not a fair opponent for the two online policies, and the
report says so per row rather than leaving a reader to assume a like-for-like
race. They are also both accessibility-BLIND -- neither knows a wheelchair
position exists -- so their equipment violations are reported as a finding about
what the current planner does under an equipment model, never as a defect in
their own terms.

STATUS. The Cordeau instances are SYNTHETIC academic benchmarks and the
accessibility labels on them are ASSIGNED by this harness, not observed: the
published files carry no accessibility attribute at all (ADR-0065). Every result
here supports ALGORITHMIC claims only. Nothing is Validated, nothing is evidence
about any real operator's service, riders, vehicles or costs, and the
stratified figures in particular must never be quoted as a statement about real
disabled riders' access.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from packages.decide.capability import ortools_capability
from packages.decide.capacity_value import (
    build_ensemble,
    prior_from_observed,
)
from packages.decide.compatibility import (
    ASSIGNED_ACCESSIBILITY_NOTE,
    assign_accessibility,
    build_compatibility_graph,
)
from packages.decide.darp_loader import find_benchmark_archive, load_zip_instance
from packages.decide.darp_solver import solve_darp
from packages.decide.pooling import (
    WHEELCHAIR,
    diff_plans,
    evaluate,
    evaluate_plan,
    plan_online,
    routes_from_solution,
)

_HERE = Path(__file__).resolve().parent
DEFAULT_INSTANCES = ("a3-18", "a4-16", "a4-24")


def run_instance(
    name: str,
    *,
    seeds: tuple[int, ...],
    accessible_vehicles: int,
    wheelchair_share: float,
    capacity_weight: float,
    plan_draws: int,
    plan_scenarios: int,
    eval_draws: int,
    eval_scenarios: int,
    lns_iterations: int,
    cpsat_time: float | None,
) -> dict:
    archive = find_benchmark_archive()
    instance = load_zip_instance(archive, name)
    profile = assign_accessibility(
        instance,
        seed=1,
        wheelchair_share=wheelchair_share,
        accessible_vehicles=accessible_vehicles,
    )

    t0 = time.perf_counter()
    graph = build_compatibility_graph(instance, profile, max_group_size=3)
    graph_s = time.perf_counter() - t0

    # ONE evaluation ensemble, fixed seed, shared by every planner and every
    # arrival order. Comparing plans against different draws would let scenario
    # noise decide the comparison.
    eval_prior = prior_from_observed(instance, profile, range(1, instance.num_requests + 1))
    eval_ensemble = build_ensemble(
        instance, profile, eval_prior, draws=eval_draws, scenarios=eval_scenarios, seed=9_001
    )

    rows: list[dict] = []
    diffs: list[dict] = []
    for seed in seeds:
        print(f"    {name}: seed {seed} ...", flush=True)
        baseline = plan_online(instance, profile, seed=seed, capacity_weight=0.0)
        candidate = plan_online(
            instance,
            profile,
            seed=seed,
            capacity_weight=capacity_weight,
            draws=plan_draws,
            scenarios=plan_scenarios,
        )
        mb = evaluate(instance, profile, baseline, ensemble=eval_ensemble)
        mc = evaluate(instance, profile, candidate, ensemble=eval_ensemble)
        rows.append({"information": "online", **mb.to_record(), "wall_time_plan_s": baseline.wall_time_s})
        rows.append({"information": "online", **mc.to_record(), "wall_time_plan_s": candidate.wall_time_s})
        diffs.append(
            {
                "seed": seed,
                **diff_plans(instance, profile, mb, baseline.routes, mc, candidate.routes).to_record(),
            }
        )

    # --- the offline yardsticks. Different information regime; labelled. ----
    #
    # BUDGET HONESTY, inherited from ADR-0060: the pure-Python LNS is on a SHORT
    # LEASH here (its construction phase alone is not interruptible, so the wall
    # cap only binds inside the improvement loop). Its objective is its answer at
    # this budget, not its best, and it is present as an accessibility-blind
    # comparison rather than as a distance champion.
    offline: list[dict] = []
    print(f"    {name}: lns ...", flush=True)
    t0 = time.perf_counter()
    lns = solve_darp(instance, seed=1, max_iterations=lns_iterations, time_limit_s=30.0)
    lns_routes, lns_sched = routes_from_solution(instance, lns)
    m = evaluate_plan(instance, profile, lns_routes, lns_sched, policy="lns", seed=1,
                      ensemble=eval_ensemble)
    offline.append({
        "information": "offline (sees every request before committing to any)",
        "accessibility_blind": True,
        "wall_time_plan_s": round(time.perf_counter() - t0, 3),
        **m.to_record(),
    })

    if cpsat_time is not None and ortools_capability().available:
        from packages.decide.cpsat_darp import solve_darp_cpsat

        print(f"    {name}: cpsat ...", flush=True)
        t0 = time.perf_counter()
        outcome = solve_darp_cpsat(instance, seed=1, max_deterministic_time=cpsat_time)
        if outcome.solution is not None:
            r, s = routes_from_solution(instance, outcome.solution)
            m = evaluate_plan(instance, profile, r, s, policy="cpsat-darp", seed=1,
                              ensemble=eval_ensemble)
            offline.append({
                "information": "offline (sees every request before committing to any)",
                "accessibility_blind": True,
                "lower_bound_on_distance": outcome.lower_bound,
                "certified_optimal_within_lattice_tolerance": outcome.certified_optimal,
                "lattice_tolerance": outcome.lattice_tolerance,
                "wall_time_plan_s": round(time.perf_counter() - t0, 3),
                **m.to_record(),
            })
        else:
            offline.append({
                "policy": "cpsat-darp",
                "no_solution": outcome.detail,
                "lower_bound_on_distance": outcome.lower_bound,
            })

    return {
        "instance": name,
        "vehicles": instance.num_vehicles,
        "requests": instance.num_requests,
        "vehicle_capacity": instance.vehicle_capacity,
        "max_ride_time": instance.max_ride_time,
        "compatibility_graph": {**graph.to_record(), "build_wall_time_s": round(graph_s, 3)},
        "plans": rows,
        "offline_yardsticks": offline,
        "decision_diffs": diffs,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--instances", nargs="*", default=list(DEFAULT_INSTANCES))
    ap.add_argument("--seeds", nargs="*", type=int, default=[1, 2, 3])
    ap.add_argument("--accessible-vehicles", type=int, default=1)
    ap.add_argument("--wheelchair-share", type=float, default=0.35)
    ap.add_argument("--capacity-weight", type=float, default=1.0)
    ap.add_argument("--plan-draws", type=int, default=3)
    ap.add_argument("--plan-scenarios", type=int, default=10)
    ap.add_argument("--eval-draws", type=int, default=5)
    ap.add_argument("--eval-scenarios", type=int, default=12)
    ap.add_argument("--lns-iterations", type=int, default=300)
    ap.add_argument("--cpsat-time", type=float, default=None,
                    help="CP-SAT deterministic-time budget; omit to skip the exact yardstick")
    ap.add_argument("--out", default=str(_HERE / "pooling_results.json"))
    ap.add_argument("--summary", default=str(_HERE / "pooling_summary.md"))
    args = ap.parse_args()

    if find_benchmark_archive() is None:
        print("Cordeau DARP archive not acquired; nothing to run.")
        return 1

    started = datetime.now(timezone.utc)
    results = []
    for name in args.instances:
        print(f"  {name} ...", flush=True)
        results.append(
            run_instance(
                name,
                seeds=tuple(args.seeds),
                accessible_vehicles=args.accessible_vehicles,
                wheelchair_share=args.wheelchair_share,
                capacity_weight=args.capacity_weight,
                plan_draws=args.plan_draws,
                plan_scenarios=args.plan_scenarios,
                eval_draws=args.eval_draws,
                eval_scenarios=args.eval_scenarios,
                lns_iterations=args.lns_iterations,
                cpsat_time=args.cpsat_time,
            )
        )

    from packages.decide.darp_loader import list_zip_instances

    published = list_zip_instances(find_benchmark_archive())
    payload = {
        "generated_at": started.isoformat(),
        "harness": "benchmarks/optimization/pooling_benchmark.py",
        "STATUS": (
            "Demonstrated at most. Synthetic academic instances support ALGORITHMIC claims only. "
            "Not Validated and not close."
        ),
        "ACCESSIBILITY_LABELS": ASSIGNED_ACCESSIBILITY_NOTE,
        "settings": vars(args),
        "instances_covered": list(args.instances),
        "instances_NOT_covered": [i for i in published if i not in args.instances],
        "results": results,
    }
    Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    Path(args.summary).write_text(_summary(payload), encoding="utf-8")
    print(f"wrote {args.out}\nwrote {args.summary}")
    return 0


def _summary(payload: dict) -> str:
    lines: list[str] = []
    a = lines.append
    a("# Pooling and future capacity value -- benchmark summary\n")
    a(f"Generated {payload['generated_at']} by `{payload['harness']}`.\n")
    a("> **Status: Demonstrated at most.** The Cordeau instances are synthetic academic")
    a("> benchmarks and support ALGORITHMIC claims only. **The accessibility labels are")
    a("> ASSIGNED by the harness, not observed** -- the published instance files carry no")
    a("> accessibility attribute whatsoever (ADR-0065). No stratified figure below is")
    a("> evidence about any real disabled rider's access to service.\n")
    a("> **Framing:** this measures capacity being RELEASED, never rationed. The planner")
    a("> structurally cannot decline a rider it could serve. Read `trips_served` before")
    a("> `occupancy`: an occupancy gain paid for with somebody's trip is a defect.\n")

    a("## Decision-level results\n")
    a("Occupancy is passenger miles per vehicle mile -- the quantity that fell 10.0%")
    a("sector-wide 2015->2024 while trips got *shorter*.\n")
    a("| instance | policy | info | trips | wheelchair | ambulatory | occupancy | veh-mi/trip | acc. capacity preserved | violations |")
    a("|---|---|---|---|---|---|---|---|---|---|")
    for res in payload["results"]:
        for row in res["plans"] + res["offline_yardsticks"]:
            if "cohorts" not in row:
                continue
            wc = next(c for c in row["cohorts"] if c["cohort"] == WHEELCHAIR)
            am = next(c for c in row["cohorts"] if c["cohort"] != WHEELCHAIR)
            info = "online" if row.get("information") == "online" else "offline*"
            # `None` means not computed (a plan that served nobody, or no
            # evaluation ensemble). Printed as "n/a" rather than coerced to a
            # number -- an unmeasured cell must not read as a measured zero.
            vmt = row["vehicle_miles_per_served_trip"]
            preserved = row["accessible_capacity_preserved_scenario_trips"]
            a(
                f"| {row['instance']} | {row['policy']} (seed {row['seed']}) | {info} | "
                f"{row['trips_served']}/{row['trips_demanded']} | {wc['served']}/{wc['demand']} | "
                f"{am['served']}/{am['demand']} | {row['occupancy_pax_miles_per_vehicle_mile']:.4f} | "
                f"{'n/a' if vmt is None else format(vmt, '.2f')} | "
                f"{'n/a' if preserved is None else preserved} | "
                f"{row['feasibility_violations']} |"
            )
    a("")
    a("\\* The offline rows see **every request before committing to any**. They are a")
    a("distance yardstick, not a like-for-like opponent for the online policies, and both")
    a("are accessibility-blind -- their violation counts say what the current planner does")
    a("under an equipment model, not that they are broken in their own terms.\n")

    a("## Did the decision actually change?\n")
    a("| instance | seed | identical | moved | gained | lost | pooling changed | trips | wheelchair trips | occupancy |")
    a("|---|---|---|---|---|---|---|---|---|---|")
    for res in payload["results"]:
        for d in res["decision_diffs"]:
            a(
                f"| {res['instance']} | {d['seed']} | {d['identical_decision']} | "
                f"{len(d['requests_moved_to_another_vehicle'])} | {len(d['requests_gained'])} | "
                f"{len(d['requests_lost'])} | {len(d['requests_with_different_pooling_partners'])} | "
                f"{d['trips_served_delta']:+d} | {d['accessible_trips_served_delta']:+d} | "
                f"{d['occupancy_delta']:+.4f} |"
            )
    a("")

    a("## Compatibility graph\n")
    a("| instance | nodes | edges | hyperedges | proposals | certified | rejected by routing | rejected by equipment | isolated | equipment can bind |")
    a("|---|---|---|---|---|---|---|---|---|---|")
    for res in payload["results"]:
        g = res["compatibility_graph"]
        rej = g["rejections_by_checker"]
        a(
            f"| {g['instance']} | {g['nodes']} | {g['edges_order_2']} | {g['hyperedges_order_3plus']} | "
            f"{g['proposals_scored']} | {g['proposals_certified']} | "
            f"{rej.get('cpsat_darp.exact_schedule', 0) + rej.get('feasibility.check_darp_feasibility', 0)} | "
            f"{rej.get('compatibility.check_equipment_feasibility', 0)} | "
            f"{len(g['isolated_requests'])} | {g['equipment_layer_can_bind']} |"
        )
    a("")
    a("`isolated` counts requests with no certified sharing partner at all -- riders whose")
    a("trip cannot be pooled however good the planner is. An occupancy target that ignores")
    a("them is a target that will be met by declining them.\n")

    a("## Coverage\n")
    a(f"Covered: {', '.join(payload['instances_covered'])}.\n")
    a(f"**NOT covered** ({len(payload['instances_NOT_covered'])} of the published set): "
      f"{', '.join(payload['instances_NOT_covered'])}. Named rather than silently dropped.\n")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
