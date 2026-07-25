# ADR-0060: A solver portfolio, and the heuristic it exposed

- **Status:** Accepted
- **Date:** 2026-07-25
- **Packet:** MX-F-SOLVER-PORTFOLIO-009

## Context

`solver.py` line 24 promised "CP-SAT / MILP / SMT / a portfolio" and delivered a
hand-rolled exact-plus-greedy solver. Program F sat at ~10% depth — the largest
gap in the platform. The open question was whether ortools even installs on
Python 3.14.

## Decision

**It installs.** `ortools-9.15.6755-cp314-cp314-win_amd64.whl` — a native CPython
3.14 ABI wheel, not abi3, not a source build. So a real CP-SAT backend was built
rather than the contingency architecture.

**API drift worth recording:** ortools 9.15 renamed `CpSolver.DeterministicTime()`
to the `deterministic_time` property (and `StatusName` → `status_name`). Code
written from older documentation breaks here.

The capability check was built anyway and is exercised **by fault injection
rather than by absence** — blocking the import at the meta-path level and
evicting `ortools` from `sys.modules`.

### The bound is the point

CP-SAT works on an integer lattice where **every rounding direction makes the
model a relaxation** — travel times floored, upper bounds ceiled plus slack. So
`floor(BestObjectiveBound)/scale` is a rigorous lower bound on the true Euclidean
optimum. That is what lets the platform state a gap it **computed** rather than
borrowed from a published table.

`bound`/`gap` were deliberately **not** added to `DecisionSolution` — that type
documents bound-only-behind-a-proof, and weakening it to flatter a new feature
would be the wrong trade. They live on `CpSatOutcome`/`PortfolioReport`.

`cpsat.py` imports `_candidate_times` from `solver.py` on purpose, so both
backends discretize identically. That is what makes "the two agree on the
optimum" a meaningful cross-check rather than a coincidence.

## Consequences

CP-SAT **reproduces the published proven optima exactly**, at 0.00% gap to our
own independently computed bound:

| instance | regret-construction | LNS | cpsat-darp | our bound | published |
|---|---|---|---|---|---|
| a2-16 | could not serve all 16 | 317.710 (+7.97%) | **294.24795** | 294.247936 | 294.25 |
| a2-20 | 370.025 (+7.31%) | 350.491 (+1.64%) | **344.83407** | 344.834049 | 344.83 |
| a3-18 | 342.671 (+14.04%) | 307.605 (+2.37%) | **300.48318** | 300.483161 | 300.48 |

**The losing result is the most valuable one.** The pure-Python LNS — the solver
Program F had *before* this packet — is **1.6%–8.0% off the optimum** on every
instance we can now prove. Nobody knew, because there was nothing to measure it
against. That is only visible because the portfolio put a prover next to the
heuristic.

A second finding fell out of it: the existing eight-step route scheduler is
**sound but incomplete**, and was rejecting the very routings CP-SAT was proving
optimal. `exact_schedule` was written because on a fixed sequence every
scheduling constraint is a difference constraint, so the least fixpoint is the
minimal schedule. `darp_solver.schedule_route` is untouched and kept as fallback.

### Mutation testing found four real gaps

14 applied; **10 caught first time**. The four that survived were each a genuine
hole, now closed and re-verified RED:

1. `capability.py`'s except branch was **unreachable** with ortools installed.
2. **The pairing constraint was vacuous at K=1 — and every brute-force instance
   was K=1.** Brute force extended to K=2 plus a pairing property test.
3. **Max-route-duration was never binding** (T equalled the depot window). Half
   the generated instances now use T=240 against a 480 window, with a floor on
   how many accepted schedules come from them.
4. `certified_optimal` was **only ever asserted `True`**. Now pinned in both
   directions.

**155 new tests, 0 skipped, 0 failed.** The 110 pre-existing Program F tests pass
unmodified.

### CI now installs the extra — deliberately

ortools was **not** pinned in `pyproject.toml` (outside the packet's owned
paths), which meant every CP-SAT test would have **skipped on CI**: green, having
proved nothing, including the optimality certificates that are the entire point.
That is the exact failure mode this repo has found five times this month. Added
as a `solver` extra and installed in CI, on the same reasoning as the z3 extra.

## Honest limitations

- **The artifact covers 3 of 12 published instances.** The other nine are named
  in both the JSON and the summary as not covered. The pure-Python LNS does not
  scale — a2-20 did not finish 400 iterations in 20 minutes.
- **LNS budgets are deliberately small**, so its objective is its answer *at that
  budget*, not its best. CP-SAT's win is partly against a short leash.
- `certified_optimal` means optimal **within the lattice resolution**
  ((2n+K)/scale ≈ 3.4e-5), never absolutely. Quoting the flag without the
  tolerance overstates it.
- The relaxation means a CP-SAT route **can** be infeasible for the true
  instance. Handled via `sequence_rejected` — and it *did* fire before
  `exact_schedule` existed.
- `exact_schedule` returns `None` for both "infeasible" and "did not converge in
  the pass budget"; the caller cannot distinguish.
- **The LNS still uses the incomplete scheduler**, so it is probably rejecting
  feasible insertions and under-performing. Not switched, deliberately: it would
  change every number in `benchmarks/quality/darp_results.json` (not the packet's
  path). A known, untested opportunity.
- Strategies run **sequentially under per-strategy work budgets**, not
  concurrently under one clock — chosen for reproducibility, but total time is
  the sum and a slow strategy is not pre-empted.
- **The v0.1 Decision IR fixes ride time**, so its objective depends only on
  *which* requests are served. CP-SAT's win there is real but the problem is
  interval packing, not routing — do not read it as routing evidence.
- Cross-machine determinism is asserted from OR-Tools' documented contract, **not
  tested on a second machine**.
- Wall times in the artifact were measured on a contended machine — indicative
  only. The deterministic budgets are unaffected.
- MILP and SMT remain **Specified**. No adaptive strategy selection.
- Governance follow-ups outside the owned paths:
  `data/catalog/cordeau-darp.manifest.json` `derived_artifacts` does not list the
  two new files, and `benchmarks/README.md` does not mention `optimization/`.
- **Status is Demonstrated, not Validated.** Synthetic academic instances support
  algorithmic claims only.
