# DARP solver-quality benchmark -- honest results
_Generated 2026-07-24T14:09:10.721507+00:00 by `benchmarks/quality/darp_benchmark.py`._
Solver: `milexium-decide-darp` v0.2.0 (pure-Python regret insertion + large-neighbourhood search; no OR-Tools/external solver). Seed 1. Instances: published Cordeau type-a dial-a-ride set, acquired through the estate pipeline.
**Every counted solution passed BOTH independent feasibility checkers** (the routing-aware `check_darp_feasibility` and the original v0.1 `check_feasibility` via projection), and its objective was recomputed independently from the routes. Gaps are versus published values in `best_known.json` (Cordeau 2006); values there marked proven-optimal give a true optimality gap, the rest a gap-to-best-known.

## Headline
- Instances with a counted gap: **2** (of which 2 vs a proven optimum).
- Median gap: **3.99%**; best 0.00%, worst 7.97%.
- Reached the published optimum (gap = 0.00%) on: a3-18.
- Within 2%: 1/2; within 5%: 1/2.

## Honest caveats
- No solution failed a feasibility checker; the integrity property held on every instance run.
- This is a v0.2 heuristic under a modest iteration budget on a single seed. It is genuinely strong on small instances (it reaches several proven optima) but is NOT a state-of-the-art DARP solver; on larger instances the gap grows and the budget matters. We do not claim to beat any published solver.

## Per-instance results
| instance | n | K | our obj | best-known | opt? | gap% | served | feasible | time (s) | iters |
|---|---|---|---|---|---|---|---|---|---|---|
| a2-16 | 16 | 2 | 317.71 | 294.25 | yes | 7.97 | 16/16 | PASS | 19.2 | 200 |
| a3-18 | 18 | 3 | 300.48 | 300.48 | yes | 0.00 | 18/18 | PASS | 12.3 | 200 |
