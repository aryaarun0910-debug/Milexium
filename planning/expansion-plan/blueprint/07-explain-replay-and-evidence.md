# Milexium Explain, Replay, and Evidence

## The product wedge

Explain and Replay are not presentation layers around optimization. They are the
mechanism that connects a recommendation to:

- the information available at the time;
- versions of data, model, policy, solver, and code;
- constraints and objective trade-offs;
- alternatives actually evaluated;
- human overrides;
- the operational outcome;
- later evaluation and corrective action.

This decision-to-outcome chain is the heart of the expansion strategy.

## Three explanation types

Keep these visibly distinct:

### Forecast explanation

Why a predictive model produced an estimate. May include lags, calendar effects,
feature attribution, analogous periods, uncertainty, and limitations.

### Feasibility explanation

Which explicit constraints made an assignment or plan feasible or infeasible,
including values and thresholds.

### Selection explanation

Why one feasible plan ranked above another under a versioned objective, including
metric deltas and search limitations.

An LLM may translate structured evidence into accessible language. It cannot add a
factor, alternative, legal conclusion, or causal statement absent from the record.

## Evidence record

Required fields:

```json
{
  "decision_id": "dec_...",
  "task": "decide.assign_trip",
  "state_snapshot": "sts_...",
  "information_cutoff": "2026-07-23T06:00:00Z",
  "policy_version": "pol_...",
  "model_versions": ["mdl_..."],
  "forecast_vintages": ["fct_..."],
  "solver_version": "slv_...",
  "objective_version": "obj_...",
  "selected": "alt_3",
  "alternatives": ["alt_1", "alt_2", "alt_3"],
  "reason_codes": ["ACCESSIBLE_CAPACITY_AVAILABLE"],
  "actor": {"type": "system", "id": "svc_decide"},
  "trace_id": "trc_...",
  "previous_hash": "sha256:...",
  "hash": "sha256:..."
}
```

Each reason code has a versioned definition, observed value, comparison operator,
threshold, units, policy source, and affected entity.

## Evidence completeness

Score completeness mechanically:

- inputs pinned;
- information cut-off present;
- all required versions resolvable;
- policy tests passed;
- solver status and deadline present;
- objective recomputable;
- selected alternative present;
- comparison set described;
- override actor/reason present when relevant;
- outputs linked to eventual outcomes;
- sensitive fields correctly redacted;
- artifact hashes verify.

Completeness means the record can be reconstructed. It does not mean the decision
was good or compliant.

## Replay modes

### Exact replay

Same state, versions, seed, and environment should reproduce the same result or
explain a permitted nondeterministic tolerance.

### Historical replay

Uses only data available at the original information cut-off and compares the
recorded operation with another versioned decision policy.

### Scenario replay

Changes a declared variable such as fleet size, policy, demand scenario, or solver.
It is prospective simulation, not a claim about history.

### Incident replay

Reconstructs a disputed trip or operational exception and all preceding revisions,
communications, assignments, and outcomes.

## Baseline hierarchy

Use the strongest available baseline:

1. actual historical operation with verified outcome fields;
2. incumbent schedule exported before execution;
3. current Milexium champion;
4. deterministic heuristic;
5. fictional reference-agency baseline.

Never compare to a deliberately weak baseline when a stronger one is available.
Never combine synthetic and real metrics in one headline without labels.

## Counterfactual limits

Historical replay holds many behaviors fixed that would change in reality:

- dispatchers react to recommendations;
- traffic and dwell times respond to route changes;
- riders cancel or no-show differently;
- providers accept or reject assignments;
- vehicles break down;
- future bookings arrive after the cut-off.

Therefore report:

- simulated difference under stated assumptions;
- sensitivity range;
- information cut-off;
- exogenous variables held fixed;
- missing behavior;
- whether the metric is observed, derived, or simulated.

Use "replay suggests" rather than "Milexium would have saved."

## Domain metrics

Core replay metrics:

- requests, served trips, and unassigned/denied classifications;
- on-time pickups and drop-offs under the agency's definitions;
- missed trips;
- ride and excess ride time;
- requested/negotiated-window adherence;
- wheelchair/equipment fulfillment;
- deadhead time and miles;
- revenue hours/miles;
- utilization and passengers per revenue hour;
- driver overtime and break violations;
- plan changes after dispatch;
- operator overrides and reason distribution;
- evidence completeness and time-to-reconstruct.

FTA materials make the review surface concrete: agencies may be examined on
negotiated times, denials, missed trips, on-time performance, and excessively long
trips. Milexium should encode the agency's definitions and source records, not
market a generic "ADA score."
[FTA ADA review guide](https://www.transit.dot.gov/sites/fta.dot.gov/files/docs/regulations-and-guidance/safety/triennial-reviews/69491/fy18-comprehensive-review-guide-section-12-americans-disabilities-act-complementary-paratransit.pdf)

## Evidence exports

### Single-trip case file

- redacted identity/reference;
- request and revisions;
- requested/negotiated/scheduled/actual timeline;
- assignments and alternatives;
- policies and constraints;
- dispatcher changes;
- service outcome and complaint/corrective-action link;
- manifest and verification instructions.

### Period review

- metric definitions;
- numerator/denominator and exclusions;
- trend and slice tables;
- classification changes;
- unresolved data-quality issues;
- evidence completeness;
- version changes during the period.

Support JSON as authority, CSV for analysis, and PDF/HTML as a rendered view.
Signed manifests and hashes allow recipients to verify file integrity.

## Replay acceptance criteria

- Re-running the same deterministic fixture produces the same evidence hash.
- A mutation, deletion, or reordering is detected.
- Historical replay rejects data recorded after the information cut-off.
- Metrics recompute from exported records.
- Redaction tests prevent rider identity, exact home location, and sensitive notes
  from entering general exports.
- A reviewer can trace a metric to events and source imports.
- The report states whether every comparison is observed, derived, or simulated.

