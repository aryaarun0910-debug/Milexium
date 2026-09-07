# Milexium Transport Intelligence Benchmark

## Purpose

The benchmark should become the neutral evaluation surface for transport models,
solvers, policies, and evidence systems. Its job is to make claims comparable and
reproducible—not to manufacture a leaderboard Milexium is guaranteed to win.

## Benchmark tracks

### A. Aggregate demand forecasting

- NYC Access-A-Ride borough-hour demand;
- Chicago TNP community-area-hour demand;
- nationwide NTD agency-month demand response;
- MTA bus route-hour and subway station-hour generalization evidence.

Evaluate:

- seasonal-naive and recent-value baselines;
- MAE/RMSE and a stated count/distribution metric;
- R² only with context;
- interval coverage and width;
- error by horizon, zone, season, demand level, and disruption regime;
- cold-start agency/zone performance;
- training/inference cost and latency.

The benchmark must preserve the current finding that a simpler production model
can beat a larger neural model.

### B. Trip-duration and travel-time prediction

Use public ride/trip data only for the transport modes it actually represents.
Evaluate time-of-day, geography, weather/traffic information available at issue
time, and out-of-distribution conditions. Do not label rideshare duration as
paratransit dwell or boarding time.

### C. Static dial-a-ride optimization

Use recognized DARP/pickup-and-delivery benchmark instances plus deterministic
Milexium reference-agency cases. Cordeau's DARP work defines the problem around
origin/destination requests, time windows, capacities, and ride-time concerns;
public academic instance collections can test solver correctness and performance.
[Cordeau paper](https://pubsonline.informs.org/doi/10.1287/opre.1060.0283) ·
[TU Wien instance collection](https://www.ac.tuwien.ac.at/research/problem-instances/)

Evaluate:

- valid/invalid solution;
- requests served;
- objective vector, bound and gap where available;
- passenger ride/excess time;
- route/deadhead time;
- vehicle and driver use;
- runtime and memory;
- determinism and run-to-run distribution;
- evidence completeness.

### D. Dynamic disruption

Reveal bookings and events over simulated operational time:

- late/cancelled/no-show requests;
- traffic/travel-time changes;
- vehicle breakdown;
- driver absence;
- urgent request;
- facility delay.

Evaluate feasibility, service quality, computation deadline, and plan churn. The
frozen horizon and information availability are part of the instance.

### E. Replay and evidence

Seed a known event history and deliberate defects:

- missing event;
- mutated alternative;
- late-arriving fact used early;
- changed policy alias;
- incomplete override;
- PII leaked into export.

Evaluate exact replay, cutoff enforcement, tamper detection, metric
recomputation, redaction, and completeness.

### F. Adapter conformance

Given source fixtures, verify:

- field mapping;
- timezone and DST behavior;
- ID stability;
- corrections/deletions;
- null/zero/suppression handling;
- reconciliation;
- semantic-loss report;
- round-trip behavior where supported.

## Data ladder

| Tier | Data | Valid claim |
|---|---|---|
| 0 | Hand-written unit fixtures | Code semantics |
| 1 | Deterministic fictional reference agency | End-to-end demonstration |
| 2 | Academic optimization instances | Solver comparison on specified problems |
| 3 | Public aggregate paratransit | Aggregate demand forecasting |
| 4 | Public trip-level mobility proxy | Generic mobility/travel-time research with domain caveats |
| 5 | De-identified/limited operator sample | Shadow evaluation inside contract scope |
| 6 | Longitudinal operator operations and outcomes | Product value and deployment learning |
| 7 | Multi-operator, permissioned normalized corpus | Generalization and moat claims within permissions |

No lower tier inherits the claims of a higher tier.

## Reproducibility manifest

Every result contains:

- task and benchmark version;
- dataset source/license/checksum;
- preparation code commit and environment lock;
- split and information cut-off;
- model/solver/policy version;
- seed and hardware;
- training and inference budget;
- metric definitions;
- raw per-instance results;
- known limitations;
- command to reproduce;
- artifact hashes.

## Evaluation protocol

1. Pre-register task, split, metrics, baseline, and promotion rule.
2. Freeze hidden test labels or use a reproducible external evaluator.
3. Prevent tuning against the final set.
4. Run temporal and cross-entity tests where appropriate.
5. Report all planned slices and failed runs.
6. Compare operational metrics as well as prediction loss.
7. Require solver-independent feasibility checks.
8. Separate observed, derived, and simulated outcomes.
9. Record compute and latency.
10. Publish a model/solver card for each submission.

## Leaderboard design

Do not collapse the benchmark to one score. Publish a Pareto view:

- accuracy or objective quality;
- uncertainty/calibration;
- feasibility;
- runtime/cost;
- robustness;
- reproducibility;
- evidence completeness.

Separate tracks and hardware classes. Mark non-reproducible, proprietary, and
externally hosted submissions. Milexium's own entries receive no special rules.

## Public model and solver registry

Registry names describe task and evidence, not branding:

```text
forecast-demand-aar-borough-hour
forecast-demand-ntd-agency-month-cold-start
solver-darp-reference-ortools
policy-paratransit-reference-us
```

Each entry includes descriptor, license, source or endpoint, artifact hash,
benchmark results, intended/prohibited use, compatibility, resource envelope,
security status, maturity, and last evaluation.

Do not publish a `no-show` or `capacity-risk` model until it exists and has an
appropriate dataset. A registry full of placeholders harms credibility.

## Research program

Prioritized reports:

1. **Information-time-correct demand forecasting for paratransit.**
   Baselines, rolling evaluation, calibration, and what aggregate data can prove.
2. **Cross-city and cold-start transfer.**
   When pretraining helps, which covariates transfer, and when local fine-tuning is
   still required.
3. **Constraint-native explanations for dial-a-ride scheduling.**
   A formal evidence vocabulary, alternative coverage, and reproducibility.
4. **Temporal replay for transport decisions.**
   Bitemporal state, late-arriving facts, deterministic reconstruction, and limits
   on counterfactual interpretation.
5. **Operational value of probabilistic capacity forecasts.**
   How intervals change reserves, served trips, overtime, and plan stability.
6. **Adapter semantic loss.**
   How operational meaning is preserved or lost across common transit formats.

Each report needs code, data-access instructions, manifests, negative findings,
and a claims/limitations section. Prefer credible engineering reports over
premature claims of novel academic theory.

## Success signal

The benchmark matters when an external team reproduces a result, reports a bug,
submits a baseline, or uses the conformance suite. Downloads without completed
runs are weaker evidence.

