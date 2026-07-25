# Solver-portfolio benchmark -- honest results
_Generated 2026-07-25T19:15:23.089639+00:00 by `benchmarks/optimization/portfolio_benchmark.py`._

Portfolio v0.3.0: `regret-construction`, `lns` (pure-Python ruin-and-recreate), `cpsat-darp` (OR-Tools CP-SAT on a lattice relaxation). OR-Tools: ortools 9.15.6755 imported successfully. Seed 1. Python 3.14.2.

**Every counted routing passed BOTH independent feasibility checkers** (the routing-aware `check_darp_feasibility` and the original v0.1 `check_feasibility` via projection), and its objective was recomputed independently from the routes.

## What the two gap columns mean
- **gap vs our bound** -- our incumbent against a lower bound this repository PROVED for itself (CP-SAT on a relaxation whose rounding directions make the bound rigorous). Borrows nothing from the literature. This is the honest headline number.
- **gap vs published** -- our incumbent against Cordeau (2006), for comparability only.

## Headline
- Instances with a self-computed gap: **3**.
- Median gap to our own proven bound: **0.00%**; best 0.00%, worst 0.00%.
- Median gap to the published value: **0.00%**; best -0.00%, worst 0.00%.
- Strategy that produced the returned routing: `cpsat-darp` x3.
- Instances where CP-SAT contributed a rigorous lower bound: **3/3**.
- **NOT COVERED BY THIS RUN**: a2-24, a3-24, a3-30, a3-36, a4-16, a4-24, a4-32, a4-40, a4-48. No result was produced for them here, so nothing in this file says anything about them either way.

## Integrity

- Routings rejected by a checker: **0**.
- Bound-above-published-optimum defects: **0** (none).
- All runs deterministic (work budgets, not wall clocks): **True**.

## Honest caveats

- These are SYNTHETIC academic instances. They support algorithmic claims only. Nothing here is operational evidence, and no number in this file may be cited as validation against a real operator's service. Program F remains **Demonstrated**, not Validated.
- CP-SAT solves a LATTICE RELAXATION of each instance (travel times floored, upper bounds loosened). That is what makes the bound rigorous, but it also means a routing CP-SAT considers optimal is not automatically feasible for the true instance -- each is re-scheduled in exact arithmetic and re-checked, and rejected if it fails.
- `certified_optimal` means optimal WITHIN THE LATTICE RESOLUTION (a computed tolerance of (2n+K)/scale), not absolutely.
- CP-SAT closes only the smallest instances. On larger ones its bound is weak and the gap reported against it overstates the true distance from optimality -- a weak bound makes us look worse than we are, which is the direction we prefer to be wrong in.
- The heuristic budget is modest and single-seed. This is not a state-of-the-art DARP solver and no claim is made against any published solver.

## Per-instance results

| instance | n | K | winner | our obj | our bound | gap vs our bound | published | opt? | gap vs published | served | checkers | time (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| a2-16 | 16 | 2 | cpsat-darp | 294.25 | 294.25 | 0.00% | 294.25 | yes | -0.00% | 16/16 | PASS | 36.7 |
| a2-20 | 20 | 2 | cpsat-darp | 344.83 | 344.83 | 0.00% | 344.83 | yes | 0.00% | 20/20 | PASS | 43.2 |
| a3-18 | 18 | 3 | cpsat-darp | 300.48 | 300.48 | 0.00% | 300.48 | yes | 0.00% | 18/18 | PASS | 31.4 |
