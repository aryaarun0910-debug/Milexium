# Platform architecture

## Architecture principle

Build a modular monolith with strict internal contracts before building distributed
services. The architecture should make components replaceable in code; it does not
need a network boundary between every box.

```text
                 MILEXIUM CONTROL AND EVIDENCE PLANE

  Sources          Canonical state          Intelligence
┌──────────┐      ┌────────────────┐      ┌─────────────────┐
│ CSV/API  │ ---> │ MilexiumDB     │ ---> │ Core / Forecast │
│ standards│      │ versions/events│      │ model runtime   │
└──────────┘      └───────┬────────┘      └────────┬────────┘
                          │                         │
                          v                         v
                  ┌────────────────┐      ┌─────────────────┐
                  │ Evidence ledger│ <--- │ Decide / policy │
                  └───────┬────────┘      │ solver runtime  │
                          │               └─────────────────┘
                          v
                  ┌────────────────┐
                  │ Replay/evaluate│ ---> SDK, API, exports, applications
                  └────────────────┘
```

Applications—including a dispatcher console—are clients of the platform. They do
not own model, policy, solver, or evidence semantics.

## Bounded modules

| Module | Owns | Must not own |
|---|---|---|
| Connect | Reading, mapping, validation, quarantine, source lineage | Business policy or model features |
| MilexiumDB | Canonical operational state, versions, events, outcomes | Vendor-specific fields without namespacing |
| Core | Task selection, plugin execution, version resolution, safety gates | A universal predictive model |
| Forecast | Prediction tasks, vintages, intervals, calibration, monitoring | Schedule feasibility |
| Decide | Policy evaluation, constraints, objectives, solver execution | Narrative explanations |
| Explain | Structured factors, failed constraints, alternatives, objective deltas | Invented post-hoc rationales |
| Replay | Point-in-time reconstruction, scenario comparison, metric computation | Causal claims from simulation |
| Registry | Schemas, adapters, models, solvers, policies, compatibility metadata | Raw customer secrets |
| Evidence | Manifests, hashes, export and verification | Claims of legal immutability |

Dependencies flow downward through interfaces. An adapter can depend on public
schema packages; a core domain object cannot import an Ecolane, TripSpark, or
agency-specific adapter.

## Physical deployment fabric

The reference and distributed implementations share:

- Python package and CLI for the reference implementation.
- FastAPI or equivalent for HTTP access.
- PostgreSQL plus PostGIS for transactional and geospatial state.
- SQLite only for deterministic local examples if identical behavioral tests run
  against PostgreSQL.
- Object storage for immutable source files, model artifacts, and evidence bundles.
- A transactional outbox for reliable export and asynchronous work.
- A worker process for long solver, replay, and training jobs.
- OpenTelemetry-compatible traces, metrics, and logs.

PostgreSQL supports row security policies that can enforce per-row access rules,
including default-deny behavior when row security is enabled without a matching
policy. This is useful as one layer of tenant isolation, not a substitute for
application authorization and testing. [PostgreSQL RLS documentation](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)

Event streaming, container orchestration, feature serving, graph projections,
analytical warehouses, distributed object storage, and accelerator workers are
independent deployment modules behind the same contracts. Agent swarms can build
them concurrently; deployment profiles select the modules required for local,
hosted, private-cloud, multi-region, research-cluster, and edge operation.

## Synchronous and asynchronous paths

**Synchronous path:** validate a bounded request, resolve versions, produce a
prediction or advisory decision, persist evidence, return a result. It must have a
deadline, deterministic error behavior, and a safe non-action result.

**Asynchronous path:** import large files, train models, run large replays, solve
batch manifests, generate evidence packages, and evaluate submissions. Jobs expose
status, progress, cancellation, input manifest, retry policy, and result manifest.

No API request should remain open for an unbounded solver run.

## Build versus buy

Build the transport-specific contracts and evidence semantics:

- canonical operational state;
- adapter mapping and semantic-loss reports;
- policy and constraint vocabulary;
- model/solver task contracts;
- decision alternatives and evidence completeness;
- temporal replay and domain metrics;
- conformance and benchmark suites.

Use mature infrastructure for:

- relational and geospatial storage;
- object storage;
- identity and secrets;
- optimization algorithms;
- model packaging and experiment tracking;
- telemetry;
- encryption and backups.

MLflow, for example, already provides registered model versions, aliases, tags,
signatures, and lineage to experiment runs. Milexium should add transport task,
data-availability, policy-compatibility, calibration, and approval semantics around
such a registry rather than rebuild generic model lifecycle tooling.
[MLflow registry](https://www.mlflow.org/docs/latest/ml/model-registry/workflow/)

## Architecture deployment evidence

A module has a strong separate-service case when at least one is true:

- it needs independent scaling demonstrated by production telemetry;
- it has a materially different security or data-residency boundary;
- it requires fault isolation for a named service-level objective;
- a separate team must deploy it independently;
- a customer requires a separately deployable component.

Every module still receives modular source boundaries, typed interfaces, tests,
independent version metadata, a local implementation, and a distributed
deployment specification.

## Required architecture evidence

- Context, container, and module diagrams tied to actual packages.
- Architecture decision records with trigger conditions and rejected alternatives.
- Dependency tests that prevent cross-module imports.
- A local reference deployment and one managed deployment.
- Restore and migration tests.
- A trace that connects import → state snapshot → prediction → solver run →
  decision → outcome → replay.
- Version endpoint reporting code, schema, policy, model, and solver compatibility.
