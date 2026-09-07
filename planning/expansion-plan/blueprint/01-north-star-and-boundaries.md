# North star and product boundaries

## The durable thesis

Milexium should become the model-agnostic decision infrastructure for
demand-responsive transportation:

```text
operational sources
    -> validated canonical state
    -> forecasts and uncertainty
    -> policy and feasible optimisation
    -> structured decisions and alternatives
    -> outcomes, evaluation, and replay
```

This expands the company without changing its initial product. Paratransit remains
the first domain adapter because it combines hard capacity constraints, negotiated
time windows, human overrides, expensive failure modes, and a concrete review
surface. NEMT is adjacent and adds distinct health-data, broker, payer, and
workflow contracts implemented as separate domain packages.

The expansion is a **control-plane, evidence, intelligence, and execution
strategy**. Read-only replay, advisory recommendations, controlled operational
execution, simulation, research, embedded APIs, and edge modes are all specified
in parallel. Each deployment selects the authorization mode appropriate to its
operator and evidence.

## What "unavoidable" must mean

"Unavoidable" is not a slogan and cannot mean monopoly. It is achieved when the
cheapest, safest way for another team to add transport intelligence is to use
Milexium's contracts and evaluation layer rather than rebuild them.

The thesis is working only when several of these are observable:

1. External data producers map to the Milexium schema without custom downstream
   code for every model.
2. Multiple model and solver implementations pass the same conformance suite.
3. A schedule or recommendation can be reproduced from its recorded state,
   policy, model, solver, and randomness versions.
4. Vendors or researchers submit plugins, adapters, or benchmark results.
5. Operators use replay before considering live decision automation.
6. Decision-to-outcome history improves evaluation and deployment decisions.
7. Removing Milexium would require replacing integrations, policy semantics,
   evaluation history, and evidence workflows—not merely replacing one model.

If none of these happens, Milexium is an application with an ambitious diagram.

## Current evidence versus complete platform

| Capability | Current truthful position | Complete platform | Evidence required for validated claims |
|---|---|---|---|
| Demand forecasting | Real aggregate paratransit and mobility data; strict temporal evaluation | Multi-task forecast runtime | Operator-specific, point-in-time shadow validation |
| Scheduling | Deterministic demonstration on fictional trip-level data | Replaceable constrained optimisation runtime | Public DARP benchmarks, then consented trip-level shadow data |
| Explanations | Forecast attribution plus deterministic scheduler reason codes | Constraint-native decision evidence | Alternative coverage and operator comprehension tests |
| Replay | Specified in the YC roadmap | Temporal operational replay | Reproducibility tests and baseline agreement |
| Canonical state | Initial MilexiumDB design | Versioned, open transport decision schema | Two genuinely different integrations with low semantic loss |
| Platform/SDK | Vision | Stable local SDK and hosted API | External installation and retained use |
| Defensibility | Research rigor and domain focus | Decision-to-outcome corpus and policy/integration learning | Permissioned longitudinal use across deployments |

## Non-negotiable boundaries

- Milexium does not infer ADA eligibility from age, diagnosis, geography, or a
  forecast.
- Forecasts cannot be the sole basis for denying a trip.
- A generated natural-language explanation is never the authoritative decision
  record.
- Replay is a modelled comparison, not causal proof of savings.
- A hash chain is tamper-evident, not immutable and not a compliance certificate.
- Public aggregate data validates aggregate demand tasks, not individual dispatch.
- Customer data is not pooled for training unless contracts and permissions
  explicitly allow the precise use.
- Adapters outside paratransit retain separate domain semantics, constraints,
  evaluation data, and buyer/workflow definitions rather than contaminating the
  shared core.

## Company identity

**Category:** transport decision infrastructure.

**Company line:** Milexium turns transport data into forecasts, feasible actions,
and auditable decisions through a model-agnostic runtime.

**Beachhead line:** Milexium helps paratransit operators forecast capacity,
evaluate scheduling decisions, and reconstruct why operational exceptions occurred
without replacing their dispatch system on day one.

**Developer line:** Build and evaluate demand-responsive transport models and
solvers against one versioned operational-state and evidence contract.

## The expansion rule

The shared core owns only concepts that are invariant across at least two valid
adapters: identity, time, space, resources, requests, forecasts, policies, plans,
decisions, provenance, and outcomes. Sector-specific rules stay in adapters.

This prevents an airport, campus, or fixed-route concept from contaminating the
paratransit domain simply because it might be useful later.
