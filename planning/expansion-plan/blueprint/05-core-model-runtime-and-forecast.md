# Milexium Core and Forecast

## Core is a task runtime, not one model

Milexium Core resolves a transport task to a compatible implementation, validates
its inputs, runs it within operational limits, evaluates its output, and records
enough evidence to reproduce or reject the result.

Tasks stay narrow:

- `forecast.demand`
- `forecast.trip_duration`
- `forecast.no_show`
- `forecast.cancellation`
- `forecast.lateness`
- `forecast.capacity_shortage`
- `forecast.deadhead`
- `forecast.overtime`
- `forecast.facility_arrivals`

The existence of a task name does not mean Milexium has a validated model for it.
The registry exposes maturity per implementation.

## Task contract

Every task specification defines:

| Contract area | Required content |
|---|---|
| Scope | service types, spatial/temporal grain, horizon, output unit |
| Inputs | required/optional state, information cut-off, feature availability |
| Outputs | estimate/distribution, intervals, warnings, abstention |
| Metrics | baseline, loss, calibration, slices, operational metric |
| Safety | prohibited uses, human-review rule, fallback |
| Compatibility | schema, adapter, policy, runtime, hardware |
| Evidence | model/data version, feature snapshot, timestamps, trace, hashes |

Example response:

```json
{
  "task": "forecast.demand",
  "scope": {"zone_id": "zn_4", "interval": "2026-07-24T08:00:00Z/PT1H"},
  "estimate": 18.0,
  "interval": {"level": 0.9, "lower": 15.0, "upper": 22.0},
  "model_version": "mdl_...",
  "feature_snapshot": "fts_...",
  "generated_at": "2026-07-23T12:00:00Z",
  "valid_for": "2026-07-24T08:00:00Z",
  "quality": {"status": "pass", "warnings": []},
  "provenance": {"state_snapshot": "sts_...", "trace_id": "trc_..."}
}
```

Do not expose a universal scalar "confidence." A 0.91 probability, a 90% prediction
interval, calibration coverage, and data-quality score have different meanings.

## Plugin interface

A model plugin declares:

```text
metadata() -> ModelDescriptor
validate(input) -> ValidationReport
predict(input, deadline, seed) -> Prediction
explain(input, prediction) -> ForecastExplanation
health() -> HealthReport
```

`ModelDescriptor` includes:

- task and model family;
- intended use and prohibited use;
- model, training code, and artifact hashes;
- training/evaluation data manifests and time ranges;
- required features and information availability;
- supported schema and service adapters;
- output distribution/interval semantics;
- baseline and evaluation results;
- latency and resource profile;
- maturity and approval status.

Plugins may wrap Milexium, customer, open-source, or third-party models. Customer
plugins execute within an explicit trust and deployment boundary. A plugin cannot
read an entire tenant merely because one task invocation needs a single snapshot.

## Model resolution

Resolution is deterministic:

1. Filter by task, service adapter, schema, horizon, and required output.
2. Reject implementations whose features are unavailable at the prediction cut-off.
3. Apply tenant allowlists, residency, maturity, and risk policy.
4. Select a pinned model version or named alias such as `champion`.
5. Check input drift, missingness, and operating envelope.
6. Run with a deadline and resource budget.
7. Validate output and calibration status.
8. Return, abstain, or use a declared fallback.
9. Record the candidates, rule evaluation, selection, and result.

The router does not silently choose the most recently uploaded model.

## Forecast vintages

Store every operational forecast as a vintage:

- issue time and data cut-off;
- target interval and horizon;
- entity/spatial grain;
- estimate and distribution/interval;
- model, features, state, and calibration versions;
- eventual actual and when it became available;
- revision/correction lineage.

Evaluation queries use the vintage that genuinely existed at the historical
decision time. This prevents hindsight leakage in replay.

## Uncertainty and calibration

Each probabilistic output declares:

- what is uncertain;
- interval or distribution type;
- nominal coverage or quantile;
- calibration population and period;
- observed coverage and width;
- conditional slices;
- known shift;
- whether uncertainty feeds a decision constraint or only an advisory display.

For the current demand work, split-conformal XGBoost is the production reference
until a challenger wins on untouched temporal data and relevant operational
metrics. The transformer is not promoted because it is larger; it must win.

## Quality and abstention

A task can return:

- `PASS`: output meets input and operating-envelope rules;
- `WARN`: output is usable only with explicit warnings;
- `ABSTAIN`: no approved output because inputs or conditions are outside scope;
- `FAIL`: execution or integrity failure.

Example abstention triggers:

- required features are stale or missing;
- geography/model vocabulary is unseen and no cold-start model is approved;
- calibration has breached its threshold;
- input falls outside model limits;
- deadline exceeded without a valid fallback;
- plugin artifact or signature verification fails.

Abstention is a product capability. Fabricated precision is not.

## Champion/challenger

Challengers run in shadow mode against the same point-in-time inputs. Promotion
requires:

- pre-registered evaluation window and metrics;
- baseline and current champion comparison;
- uncertainty calibration;
- performance by geography, service type, equipment requirement, demand regime,
  and protected/sensitive proxies only where lawful and meaningful;
- latency, cost, reliability, and missing-data behavior;
- downstream operational value in replay;
- sign-off and rollback plan.

## Monitoring

Track:

- feature availability, freshness, range, and drift;
- prediction distribution and interval width;
- residual/error after outcomes arrive;
- coverage by slice and horizon;
- abstention/fallback rate;
- inference latency, error, and cost;
- model selection and alias changes;
- downstream override and constraint interaction;
- forecast usefulness, not only statistical accuracy.

Monitoring thresholds are tied to actions: warn, shadow, rollback, disable, or
recalibrate. A dashboard without response policy is not governance.

## Defensibility

Individual models will commoditize. Core becomes defensible through:

- task and compatibility contracts;
- information-time-correct feature semantics;
- deployment and approval history;
- model-to-policy-to-outcome evaluation;
- cross-vendor canonical state;
- transport-specific failure and abstention behavior.

Better external models should increase Core's value because they can enter the same
controlled evaluation and evidence path.

