# Semantic state, TurboVec, and scientific R&D

## Executive decision

Milexium should build a **semantic state layer**, but it should not build a new
general-purpose database engine. PostgreSQL/PostGIS remains authoritative,
object storage retains immutable source and model artifacts, and a vector index
is a disposable projection used for similarity retrieval.

TurboVec is a promising candidate for that projection because it offers online
ingest, low-bit vector quantisation, stable integer IDs, allow-list filtering,
deletion, and local persistence. It is not MilexiumDB by itself: it does not
provide relational constraints, bitemporal truth, transactions across domain
records, row-level tenancy, durable workflow execution, distributed replication,
or an authorization model.

The current TurboVec Python package is explicitly alpha. Its repository also has
open hardening work around atomic persistence, malformed-load validation,
encoding bounds, concurrent mutation, and release discipline. The integration
program therefore runs these workstreams in parallel:

1. specify the interface now;
2. implement the adapter, benchmark, and failure-injection suites;
3. harden or patch the pinned implementation against Milexium's gates;
4. retain exact-search and PostgreSQL vector-search fallbacks;
5. never let the index become the system of record.

## What “smart state-machine primitives” should mean

TurboVec's `state_sequences` tests exercise the lifecycle of its own index. They
are not a reusable business state-machine runtime. Milexium should implement
domain state transitions separately and make those transitions first-class
evidence.

Representative aggregates and legal transitions include:

```text
ServiceRequest:
  received -> validated -> negotiated -> accepted -> scheduled
  scheduled -> dispatched -> arrived -> boarded -> completed
  any eligible pre-service state -> cancelled
  dispatched/arrived -> failed_service

Decision:
  proposed -> policy_checked -> approved -> emitted
  proposed/policy_checked -> rejected
  emitted -> superseded

DataImport:
  received -> quarantined -> validated -> reconciled -> activated
  quarantined/validated/reconciled -> rejected
```

Every transition requires:

- aggregate ID, tenant ID, prior version, and monotonic sequence;
- valid time and recorded/system time;
- initiating actor or service identity;
- command, reason, correlation, and trace IDs;
- policy, constraint, model, feature, solver, and schema versions where relevant;
- invariant results, override authority, and referenced evidence;
- idempotency key and canonical payload hash.

The transaction writes current relational state, an immutable transition event,
and an outbox item together. Indexing is asynchronous and recoverable. A
transition is accepted by explicit guards and policies—not because a similar
vector was retrieved.

## Milexium Semantic State Index

The index stores **decision episodes**, not every raw trip row. A decision episode
is a compact representation of the information, constraints, action, and
eventual outcome surrounding a meaningful operational choice.

```json
{
  "case_id": "case_01...",
  "tenant_id": "ten_01...",
  "snapshot_id": "sts_01...",
  "aggregate_type": "service_request",
  "aggregate_id": "req_01...",
  "transition": "scheduled->dispatched",
  "decision_type": "recovery_assignment",
  "valid_at": "2026-07-23T16:05:00Z",
  "recorded_at": "2026-07-23T16:05:02Z",
  "constraint_fingerprint": "sha256:...",
  "policy_version": "pol_...",
  "model_version": "mdl_...",
  "solver_version": "slv_...",
  "embedding_model": "emb_...",
  "embedding_schema": "case-v1",
  "index_generation": "sem-2026-07-23-01",
  "outcome_refs": ["out_..."]
}
```

Only an opaque, stable numeric handle and compressed vector need live in
TurboVec. Typed metadata, permissions, source text, sensitive fields, and
outcomes stay in MilexiumDB.

### Safe query path

1. Authenticate the caller and resolve tenant/data entitlements.
2. Use SQL to select eligible case IDs by tenant, service, time, policy,
   sensitivity, and deletion status.
3. Pass only those numeric handles to the vector index allow-list.
4. Retrieve nearest candidates.
5. Rehydrate authoritative records from PostgreSQL.
6. Recheck access, validity, and staleness.
7. Present cases as evidence or input features; do not silently execute them.

This ordering prevents vector similarity from bypassing authorization or
business constraints.

### Valuable initial uses

- retrieve analogous disruption, recovery, capacity, and override cases;
- surface policy precedents and explain why an operator previously overrode a
  recommendation;
- find structurally similar cold-start services or zones;
- detect state episodes that are semantically unusual for review;
- map unfamiliar vendor fields to canonical concepts with human confirmation;
- find relevant evidence packets, incidents, and runbooks;
- supply retrieval features to a model while retaining deterministic guards.

Bad uses include calculating official KPIs, deciding eligibility, enforcing
capacity, authorizing state transitions, or treating similarity as causal proof.

## Index consistency and recovery contract

The semantic index is eventually consistent and rebuildable:

- transactional outbox events feed an idempotent indexer;
- every entry records embedding and index-generation versions;
- a reconciliation job compares authoritative eligible cases with indexed IDs;
- deletes create tombstones before physical compaction;
- rebuilds create a new generation and atomically swap a small generation
  pointer after verification;
- old generations remain available for bounded rollback;
- re-embedding uses dual-write or backfill-and-swap, never an in-place semantic
  mutation;
- replay records the generation used by the original decision.

An index outage must degrade semantic retrieval, not prevent core scheduling,
forecasting, evidence capture, or replay.

## TurboVec adoption and vendoring plan

### Gate 0: legal and provenance

TurboVec uses the MIT License, which permits use, modification, distribution,
sublicensing, and sale provided the copyright and permission notice are retained.
Record the exact upstream URL, commit, package version, license text, dependency
tree, checksums, security contacts, and local patches in an SBOM and
`THIRD_PARTY_NOTICES`.

### Gate 1: isolated adapter

Define an implementation-neutral contract:

```text
SemanticIndex
  build(generation, dimension, metric, options)
  upsert(handle, vector)
  remove(handle)
  search(query, k, allowed_handles) -> scored_handles
  save(generation)
  load(generation)
  validate(generation)
  stats()
```

Implement exact NumPy/Rust search for truth tests and a PostgreSQL/pgvector
adapter as the operational fallback. TurboVec-specific types must not escape the
adapter.

### Gate 2: benchmark on Milexium cases

Benchmark exact search, pgvector, and TurboVec with 100 thousand, 1 million, and
10 million synthetic or de-identified decision episodes. Measure:

| Dimension | Required measure |
|---|---|
| Retrieval quality | recall@1/10/50, NDCG@10, policy-precedent hit rate |
| Latency | p50/p95/p99 for unfiltered and tenant-filtered queries |
| Resource use | resident memory, persisted bytes, CPU-seconds, load time |
| Mutation | add/delete throughput, search during mutation, index lag |
| Recovery | kill during save, truncated/corrupt files, rollback, rebuild time |
| Isolation | empty/wrong tenant allow-lists, deleted IDs, stale permissions |
| Portability | Windows installation, Linux container build, CPU feature fallback |
| Determinism | stable results and artifact checksums under pinned inputs |

TurboVec's published 100-thousand-vector benchmark is evidence of potential, not
evidence of Milexium-scale production suitability.

### Gate 3: production hardening

Do not adopt the currently released build for critical persistence until atomic
save and load-validation hardening is released or independently reviewed and
backported. Stress concurrent readers and writers because open reports identify
mutation hazards in some Python integration paths.

Acceptance requires:

- zero cross-tenant retrieval in adversarial tests;
- recovery of the previous verified generation after every injected crash;
- recall loss within a product-specific bound;
- predictable p99 under representative filters and concurrent load;
- one-command reproducible Linux build and a proven Windows developer path;
- no single index corruption can damage source or canonical state.

### Dependency before fork

Prefer a version-and-commit-pinned upstream dependency. If Milexium needs fixes,
maintain a small patch queue. Create a fork only if upstream latency or product
requirements make that necessary.

If source vendoring is required, place the unmodified upstream snapshot under
`third_party/turbovec`, preserve its license, document the commit and local
patches, and use Cargo's vendoring support for transitive Rust dependencies.
Do not copy source into Milexium namespaces and lose provenance.

## Scientific R&D that can become product capability

The defensible opportunity is not to mention advanced science. It is to convert
selected methods into measurable operating primitives.

### Core architecture program

| Science | Milexium capability | Falsifiable product result |
|---|---|---|
| Formal specification and model checking | Specify transition safety/liveness, idempotency, overrides, and index reconciliation in TLA+/PlusCal | TLC finds no violation inside bounded failure scenarios; seeded bugs are detected |
| Bitemporal/event-sourced modeling | Reconstruct what was known versus what later became known | Exact replay hash matches the original information horizon |
| Process mining and conformance checking | Discover actual workflows and compare them with stated SOPs | Quantified deviation and waiting-time map from real event logs |
| Conformal uncertainty | Prediction intervals and abstention for demand, duration, and risk | Predeclared coverage and sharpness on forward-held-out periods |
| Distributionally robust/stochastic optimisation | Plans that tolerate uncertain demand, travel time, and cancellations | Lower tail-risk without unacceptable average-cost regression |
| Discrete-event simulation | Counterfactual fleet, facility, and dispatch experiments | Backtest fidelity against held-out operational days |
| Online change-point/drift detection | Detect changed demand, vendor semantics, or model residuals | Known synthetic and historical shifts detected within a stated delay |

### Operator-data science program

| Science | Product use | Required evidence |
|---|---|---|
| Survival/hazard models | probability and timing of cancellation, no-show, delay, or recovery | Correct censoring, temporal validation, calibration by subgroup |
| Bayesian hierarchical partial pooling | cold-start estimates across services, zones, agencies, and facilities | Beats both global pooling and isolated local estimates |
| Causal inference and uplift | estimate whether reminders, negotiation, buffering, or interventions change outcomes | Identified intervention, overlap checks, sensitivity analysis, preferably randomized rollout |
| Case-based reasoning | explain recommendations through analogous prior cases | Retrieval relevance plus operator trust; never substitutes for constraint validation |
| Multi-objective/Pareto optimisation | make cost, on-time performance, equity, burden, and resilience trade-offs explicit | Operator-approved objective definitions and stable frontier behavior |

### Frontier research program

- federated analytics and differential privacy with a cross-tenant schema,
  threat model, privacy accountant, and learning benchmark;
- optimal transport/domain adaptation with cross-city baselines and
  negative-transfer tests;
- knowledge graphs as a derived relationship view, not a competing source of
  truth;
- reinforcement learning inside validated simulators, constrained action
  spaces, shadow environments, and off-policy evaluation;
- neurosymbolic systems joining learned proposal models with explicit policies,
  constraint solvers, and proof or executable verifiers;
- adaptive inference, test-time learning, and parameter-delta memory with
  tenant isolation, versioning, evaluation, expiry, and rollback;
- autonomous experiment and evolutionary improvement through Milexium Forge;
- software-to-silicon compilation for stable, repeatedly profiled kernels.

## Research operating system

Every R&D idea needs a one-page protocol:

1. operational decision being improved;
2. current baseline and dataset;
3. hypothesis and measurable benefit;
4. leakage-safe temporal evaluation;
5. safety, equity, and failure metrics;
6. computational and data budget;
7. integration point and rollback path;
8. promote, iterate, or kill threshold.

Research graduates into the product only when it has a versioned implementation,
reproducible evaluation, monitoring contract, owner, and customer-visible value.
That discipline is more defensible than accumulating exotic algorithms.
