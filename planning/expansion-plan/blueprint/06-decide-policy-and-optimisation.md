# Milexium Decide: policy and feasible optimisation

## Purpose

Decide converts forecasts and current state into feasible, reviewable actions.
It is not a single optimizer and it must never turn a forecast directly into an
operational denial.

```text
state + forecast vintages + policy version + objective version
    -> validated decision problem
    -> constraint evaluation
    -> solver candidates
    -> best known feasible plan or explicit no-plan
    -> alternatives, reasons, evidence, and fallback
```

## Decision task catalog

- `decide.assign_trip`
- `decide.build_manifest`
- `decide.rebalance_fleet`
- `decide.allocate_capacity`
- `decide.adjust_shift`
- `decide.recover_disruption`
- `decide.compare_plans`

`decide.accept_or_reject` should not be a generic automation endpoint. Acceptance
or denial semantics vary by law, agency policy, eligibility, booking negotiation,
and service availability. Milexium may test feasibility and produce evidence; the
authorized workflow owns the consequential action.

## Separate policy, constraints, and objectives

**Policy** is a versioned, human-approved statement of operational rules and
preferences.

**Constraints** are executable checks derived from policy and physics.

**Objectives** rank feasible solutions.

These must not be collapsed into opaque weights.

### Hard constraints

Typical paratransit hard constraints:

- pickup precedes drop-off;
- vehicle/equipment capacity at every leg;
- equipment compatibility;
- driver shift and break rules;
- depot/start/end conditions;
- requested/negotiated pickup and appointment windows as configured;
- maximum ride-time rule;
- vehicle availability;
- no duplicate service;
- locked or already executed actions;
- provider/service-area permissions.

### Soft constraints and objectives

- pickup/drop-off lateness within permitted policy;
- excess ride time;
- deadhead time and miles;
- driver overtime;
- number of vehicles or providers used;
- schedule stability;
- passenger transfers;
- utilization balance;
- risk reserve for uncertain demand;
- operator-defined service equity objectives.

Objectives should be lexicographic where priorities are categorical:

1. valid policy and hard feasibility;
2. serve required trips;
3. protect service quality;
4. reduce deadhead/overtime/cost;
5. minimize disruption to a published manifest.

Weighted objectives are allowed only with named units, scaling, sensitivity tests,
and a versioned approval.

## Policy representation

A policy package contains:

- jurisdiction and service scope;
- effective/expiry interval;
- human-readable source and owner;
- machine-executable rules;
- test cases and expected outcomes;
- precedence/conflict rules;
- approval and change history;
- adapter-specific mappings;
- reason-code mappings;
- known non-automatable judgments.

Policies are code and evidence. Every change runs regression fixtures, including
boundary cases and previously disputed decisions.

## Solver interface

```text
capabilities() -> SolverDescriptor
validate(problem) -> ValidationReport
solve(problem, deadline, seed, warm_start) -> SolutionSet
explain(problem, solution_set) -> ConstraintEvidence
```

`SolverDescriptor` declares problem classes, supported constraint vocabulary,
optimality/bound behavior, determinism, warm starts, incremental updates, scale
envelope, license, and resource needs.

Potential implementations:

- OR-Tools routing or CP-SAT;
- mixed-integer programming;
- Timefold constraint solving;
- greedy construction plus local search;
- customer or third-party solver;
- learned policy only behind the same feasibility validator.

Timefold illustrates the adjacent platform risk: it offers an Apache-licensed
constraint solver and managed routing/scheduling models with validation and
explainability. Milexium must therefore differentiate through transport state,
policy semantics, temporal evidence, replay, and domain evaluation—not by claiming
generic optimization APIs are unique.
[Timefold documentation](https://docs.timefold.ai/)

## Solution result

Every result includes:

- solver and problem versions;
- status: optimal, feasible, infeasible, timeout-with-incumbent,
  timeout-without-incumbent, invalid, or failed;
- start/end, runtime, seed, hardware class;
- objective vector and units;
- bound/gap when meaningful;
- assignments and unassigned requests;
- hard/soft constraint results;
- warnings and fallback use;
- state, forecast, policy, travel-time, and code references.

Never label a heuristic result optimal. Never hide a timeout behind `success=true`.

## Alternative evidence

It is usually impossible to persist every combinatorial alternative. Define the
comparison set:

- incumbent/historical assignment;
- selected plan;
- top-k solver candidates where available;
- operator-edited plan;
- locally generated counterfactual assignments for the disputed trip;
- alternatives explicitly requested by a reviewer.

For each alternative, record:

- whether it was generated and evaluated;
- exact hard constraints failed;
- observed values and thresholds;
- objective deltas if feasible;
- which later decisions it would disturb;
- search limitations.

The explanation must say "not evaluated" when the solver never considered a named
alternative.

## Disruption and rolling re-optimization

The operational problem changes after dispatch begins. Define:

- a freeze horizon for imminent actions;
- locked completed/in-progress actions;
- disruption triggers;
- re-optimization frequency and debounce;
- maximum acceptable plan churn;
- warm-start behavior;
- operator approval threshold;
- rollback to last accepted manifest.

Schedule stability is a first-class objective. A mathematically better plan that
causes operational chaos may be worse.

## Safe degradation

On missing travel times, stale vehicle state, solver failure, or timeout:

1. preserve already accepted and imminent assignments;
2. return no automatic change if hard feasibility cannot be proven;
3. use a deterministic, tested fallback only inside its declared envelope;
4. surface affected requests and exact missing information;
5. record the failure and human response;
6. never transform uncertainty into a silent constraint relaxation.

## Verification

Every solution is checked by a solver-independent validator. Property tests cover:

- capacity throughout the route, not only per request;
- pickup/drop-off precedence;
- time and appointment windows;
- maximum ride time;
- shift and break constraints;
- locked actions;
- uniqueness;
- objective recomputation;
- deterministic replay under pinned inputs.

Benchmark runtime, feasibility, quality, and stability across instance sizes and
time budgets. Statistical performance does not excuse an invalid schedule.

