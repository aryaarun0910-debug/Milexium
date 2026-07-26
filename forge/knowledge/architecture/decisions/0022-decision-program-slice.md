# ADR-0022: Decision program slice — IR + independent feasibility checker + solver (Program F v0.1)

- **Status:** Accepted
- **Date:** 2026-07-24

## Context

Phase 1 needs a Decision program slice proving the `blueprint/06`/Program F
contract properties. There is a **separate, founder-owned** scheduling task in
`forge/knowledge/docs/MASTER_ROADMAP.md` and a demo greedy scheduler in `forge/business/reference_agency/`.
This slice is the expansion's Decision *contract* — additive, in
`metis/decide/`, explicitly **not** "the" scheduler and not a replacement for
either; it never touches `forge/business/reference_agency/` or the YC materials.

## Decision

`metis/decide/`:

- **Decision IR** (`ir.py`): `RideRequest` (pickup/dropoff windows,
  `needs_wheelchair`, `party_size`, fixed `nominal_ride_time_minutes`,
  `max_ride_time_minutes`, `must_serve`), `DecisionVehicle` (composes canonical
  `Vehicle` capacity + driver shift), `DecisionPolicy` (objective weights, time
  grid, search budget, exact/greedy switch), `DecisionSolution` (assignments,
  denials with `ReasonCode` tuples, canonical `ScheduleRunStatus`, objective,
  bound, gap, seed, and a `proven_optimal` property true only when status is
  OPTIMAL **and** gap == 0).
- **Solver** (`solver.py`, pure Python, no new dependency — `ortools` was NOT
  added): exact branch-and-bound over pickup times on the policy grid (small
  instances) with admissible pruning → OPTIMAL+gap0 or INFEASIBLE (proven via a
  `must_serve` mandate that can't be scheduled); on exhausting the node budget →
  TIMEOUT with an incumbent but **no bound/gap** (structurally cannot label a
  timeout incumbent OPTIMAL — the named `blueprint/15` failure mode); greedy
  fallback (large instances) → FEASIBLE, no bound/gap. Deterministic via a
  stable sha256 tie-break (reproducible across `PYTHONHASHSEED`).
- **Independent feasibility checker** (`feasibility.py`): imports only
  `canonical.vocab` + `decide.ir` — **never the solver** (confirmed: the
  dependency runs one way, solver→checker via a self-audit before returning).
  Re-derives every hard constraint (precedence, windows, max ride time, shift
  containment, wheelchair-on-non-accessible-vehicle, capacity via an independent
  sweep-line over onboard intervals by type) from the raw IR, returns
  `Violation`s carrying canonical `ReasonCode`s. Structural malformedness
  (unknown id, double assignment, served-and-denied) raises `MalformedSolution`,
  distinct from a well-formed-but-infeasible solution. Adversarial tests
  hand-build every solution under test (solver never called), proving the
  checker validates solutions it did not produce.

## Consequences

- The load-bearing Program F properties hold and are tested: generator/checker
  separation is real (one-way import, verified); no accepted result violates a
  hard constraint (property test over 50 seeded capacity-overload instances);
  honest status (a timeout incumbent is never OPTIMAL, `proven_optimal` cannot
  be spoofed because TIMEOUT/greedy never populate bound/gap).
- Exists (v0.1): the IR, grid-exact B&B + greedy fallback, honest status, the
  independent checker. Optimality is proven **relative to the time grid** — an
  honestly bounded claim, stated in docstrings.
- Not built (Specified): CP-SAT/MILP/SMT/heuristic-portfolio backends, a
  travel-time matrix and detour-driven ride-time inflation (v0.1 uses a fixed
  nominal ride time; pickup instant is the only continuous DOF).
- Reconciliation flagged: this slice does not persist canonical
  `decision_alternatives` rows (the standing "no store method" gap) — its
  `Denial.reason_codes` mirror `DecisionAlternative.failed_constraints`, so
  wiring `DecisionSolution` → `ScheduleRun` + `DecisionAlternative` persistence
  is the natural next step. This does not resolve, and must not be read as
  resolving, the founder-owned scheduler ownership question.
