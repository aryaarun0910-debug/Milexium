# Parallel execution roadmap

## Operating model

This roadmap is dependency-based, not calendar-based. All programs can run
concurrently through agent swarms once their input contracts, owned paths, test
fixtures, and acceptance commands exist.

The roadmap contains the complete intended system. Evidence gates decide
promotion and integration; they do not prevent parallel research or
implementation.

## Program graph

```text
Canonical contracts ─┬─> Connect adapters ────────┐
                     ├─> MilexiumDB/state ────────┤
                     ├─> Policy/Decision IR ──────┤
                     ├─> Evidence/Experience IR ──┤
                     └─> Formal invariants ───────┤
                                                  v
Data estate ─> Features ─> Forecast ─> Decide ─> Verify ─> Explain/Replay
     │                         │          │          │           │
     └──────────────> Simulation/world models <─────┘           │
                               │                                │
                               v                                v
                        Experience Fabric ───────────────> Forge
                               │                                │
                               └────────> Runtime/cost model <──┘
                                                │
                              CPU/GPU/DPU/FPGA/ASIC backends
```

## Program A: canonical transport substrate

Deliver:

- canonical bounded contexts and typed identifiers;
- explicit requested, negotiated, scheduled, predicted, and actual time fields;
- bitemporal records and immutable corrections;
- domain state machines and idempotent commands;
- policy, metric, constraint, and sensitivity vocabularies;
- external identity mapping and semantic-loss records;
- data-quality and reconciliation contracts;
- relational, event, columnar, graph, and semantic projections;
- schema migration and compatibility tooling;
- TLA+/SMT/Lean specifications for critical invariants.

Integration proof:

- heterogeneous sources map through the same canonical semantics;
- corrections preserve original decision horizons;
- generated clients and migrations pass compatibility fixtures;
- model checking finds seeded race, ordering, and invariant violations.

## Program B: Milexium Connect

Deliver:

- generic delimited, Parquet, JSON, database, batch, and streaming adapters;
- GTFS, GTFS-Realtime, Flex, TIDES, TODS, NTD, OSM, weather, traffic, and
  facility adapters;
- vendor-specific export adapter SDK;
- schema inference and mapping suggestions;
- provenance/type slicing for every canonical field;
- quarantine, validation, reconciliation, activation, and correction workflows;
- change-data capture and incremental recomputation;
- replayable import manifests and source-license registry.

Integration proof:

- every adapter passes the same conformance suite;
- malformed, late, duplicated, corrected, and semantically ambiguous inputs
  produce explicit results;
- no adapter leaks vendor-specific meanings into Core or Decide.

## Program C: MilexiumDB and semantic state

Deliver:

- PostgreSQL/PostGIS authoritative state;
- immutable object and artifact manifests;
- event history, transactional outbox, and derived projection workers;
- feature, forecast, decision, evidence, and outcome snapshots;
- semantic decision episodes and filtered compressed retrieval;
- TurboVec, pgvector, DiskANN, and exact-search adapters;
- bitmap, sketch, membership, and temporal indexes;
- retention, deletion, reindexing, reconciliation, backup, restore, and
  corruption recovery;
- hot/warm/cold storage placement and future CXL/computational-storage contracts.

Integration proof:

- exact historical reconstruction;
- zero cross-tenant retrieval in adversarial tests;
- deterministic rebuild of every derived projection;
- recovery from crashes during writes, index generation, and pointer swaps.

## Program D: Milexium Core and adaptive memory

Deliver:

- task registry and implementation-neutral model descriptors;
- feature contracts and point-in-time retrieval;
- model routing by task, tenant, geography, horizon, latency, quality, and cost;
- structured, semantic, episodic, and learned memory tiers;
- tenant-scoped LoRA/parameter-delta registry;
- test-time adaptation environment with evaluation, expiry, isolation, and
  rollback;
- state-space and long-sequence execution;
- uncertainty, abstention, calibration, drift, and change-point services;
- champion/challenger/canary promotion.

Integration proof:

- memory improves held-out long-horizon task performance;
- poisoned or degrading updates are detected and rolled back;
- tenant memory cannot affect another tenant;
- every prediction is reproducible from pinned state and artifacts.

## Program E: Milexium Forecast

Deliver:

- seasonal, statistical, tree, neural, graph, spectral, and state-space
  baselines;
- hierarchical partial-pooling models for cold-start services and geographies;
- duration, demand, cancellation/no-show, congestion, and disruption forecasts;
- survival/hazard models with censoring;
- conformal and quantile uncertainty;
- ensemble and scenario generation;
- hybrid mechanistic/learned residual models;
- symbolic regression with units, invariants, and description-length controls;
- forward temporal evaluation and subgroup calibration.

Integration proof:

- every complex model beats declared baselines on its intended regime;
- uncertainty achieves predeclared forward coverage and useful sharpness;
- drift behavior and fallback are measured;
- public, synthetic, and consented-operator evidence remain visibly separated.

## Program F: Milexium Decide

Deliver:

- Decision IR and policy packages;
- CP-SAT, MILP, SMT, MaxSAT, heuristic, approximation, and QUBO adapters;
- independent feasibility checker;
- static scheduling, rolling recovery, assignment, negotiation, fleet reserve,
  facility coordination, and resource-allocation tasks;
- decomposition, kernelization, warm starts, local neighborhoods, and
  parallel/GPU bound evaluation;
- distributionally robust and stochastic optimization;
- multi-objective/Pareto and lexicographic objectives;
- learning-guided solver selection, branching, and neighborhood policies;
- optimality gaps, lower bounds, approximation certificates, and timeout
  incumbents.

Integration proof:

- no accepted result violates hard constraints;
- every backend agrees with the independent verifier;
- learned guidance never removes exact fallback or certificates;
- tail-risk, stability, equity, and operator burden are measured with cost and
  service quality.

## Program G: Milexium Verify and formal knowledge

Deliver:

- common verifier API and signed result schema;
- schema, state, temporal, policy, constraint, numerical, statistical,
  security, replay, and hardware validators;
- TLA+ state and distributed-protocol models;
- SMT/SAT counterexample generation;
- Lean libraries for critical definitions and proof-producing transformations;
- property-based, metamorphic, fuzz, differential, and adversarial tests;
- proof-carrying decision and agent-action manifests;
- translation validation across IR lowerings;
- verifier isolation, reproducibility, and small trusted kernels.

Integration proof:

- seeded faults are caught by their intended verifier;
- generator and verifier implementations are independent;
- accepted proofs/certificates can be checked without the proposing model;
- verifier versions and limitations are recorded in evidence.

## Program H: Replay, simulation, and world models

Deliver:

- exact, historical, scenario, counterfactual, and incident replay;
- discrete-event rider, vehicle, depot, facility, queue, traffic, and dispatch
  simulation;
- synthetic agency and disruption generators;
- calibrated stochastic demand/travel/cancellation processes;
- graph/spectral and differentiable simulation surrogates;
- latent world models and imagined rollouts;
- model-predictive advisory control;
- causal and uplift evaluation for interventions;
- simulation-to-real discrepancy tracking.

Integration proof:

- replay respects original information cutoffs;
- simulator distributions match held-out operational statistics within declared
  tolerances;
- policies trained in simulation survive stress and transfer tests;
- counterfactual claims state identification assumptions and sensitivity.

## Program I: Explain, Evidence, and Experience

Deliver:

- Evidence IR and Experience IR;
- minimal provenance and causal-context slices;
- forecast, feasibility, and selection explanations;
- alternatives, constraint causes, uncertainty, and failure explanations;
- semantic precedent retrieval;
- decision, incident, period, and procurement evidence packs;
- immutable action/tool/verification traces;
- outcome linkage and operator override memory;
- selective-disclosure and machine-verifiable exports.

Integration proof:

- an independent reviewer can reconstruct what was known, proposed, verified,
  approved, executed, and observed;
- explanations remain faithful to the actual computation;
- source data, derived claims, and counterfactual assertions are distinct.

## Program J: Experience Fabric and Milexium Forge

Deliver:

- OpenEnv-style transport environment ABI;
- sandbox, snapshot, restore, reset, act, observe, verify, and replay services;
- experiment DAG and immutable result archive;
- agent curricula generated from failure clusters and synthetic worlds;
- RL rollout/reward/training adapters;
- evolutionary code/model/solver/policy/kernel search;
- population archives and diversity management;
- hidden, regression, and adversarial evaluators;
- candidate, challenger, canary, champion, rollback, and rejection lifecycle;
- cost, token, GPU, CPU, storage, and verifier accounting.

Integration proof:

- the system proposes and retains improvements on hidden distributions;
- evaluator exploits and benchmark overfitting are detected;
- rejected and negative experiments remain queryable;
- mutation agents cannot modify their promotion rules or trusted evaluators.

## Program K: hardware-aware Runtime

Deliver:

- Execution IR and hardware capability registry;
- workload profiler for bytes moved, cache behavior, SIMD, GPU occupancy,
  network, storage, and energy proxy;
- equality-saturation rewrite library and learned cost model;
- CPU/Rust, GPU/Triton/CUDA, and vectorized kernel backends;
- compressed/sparse layouts, fused kernels, captured execution, and direct I/O;
- distributed scheduling across model, verifier, simulation, and storage workers;
- eBPF observability and enforcement;
- FPGA/HLS/DPU prototypes for stable retrieval, filtering, sketches, solver
  bounds, proof, and simulation kernels;
- CIRCT/Chisel/RISC-V/ASIC contracts for recurring workloads.

Integration proof:

- optimized kernels match exact or bounded-quality reference implementations;
- end-to-end speed, cost, and data movement improve—not only microbenchmarks;
- all hardware paths retain software fallbacks and translation validation.

## Program L: confidential, private, and edge computing

Deliver:

- row, field, artifact, and execution-level tenant isolation;
- confidential-compute deployment and attestation;
- memory-safe Rust parsers, plugins, and edge runtimes;
- signed offline model/policy/state bundles;
- privacy-preserving aggregate and cross-agency computation through appropriate
  FHE, MPC, PIR, ORAM, or clean-room adapters;
- zero-knowledge proofs for selected compliance or aggregate claims;
- vehicle/depot/facility streaming inference and safe local fallback;
- key rotation, revocation, audit, and incident response.

Integration proof:

- privacy properties match explicit threat models;
- attestation and proof verification are automated;
- offline operation and resynchronization preserve state and evidence;
- confidential execution remains observable enough for safe operations without
  exposing sensitive payloads.

## Program M: APIs, ecosystem, and commercial surfaces

Deliver:

- Python, TypeScript, Rust, and HTTP/event APIs;
- CLI, local runtime, hosted cloud, embedded, private, and edge deployments;
- plugin descriptors and conformance certification;
- adapter/model/solver/environment/verifier registries;
- operator review, approval, override, replay, and reporting workflows;
- developer quickstarts and reference applications;
- procurement, security, data-readiness, and evidence packs;
- usage, value, reliability, and outcome telemetry;
- packaging for agency, provider, vendor, consultancy, research, and embedded
  channels.

Integration proof:

- external implementations pass certification without internal source access;
- deployment modes preserve the same semantics and evidence;
- product value maps to named operational decisions and measurable outcomes.

## Cross-program release criteria

A capability becomes part of the integrated Milexium platform when:

1. its normative contract is versioned;
2. implementation and independent verifier both exist;
3. conformance, adversarial, and recovery suites pass;
4. quality, latency, memory, storage, and cost are benchmarked;
5. replay and evidence are complete;
6. security, privacy, licensing, and provenance are recorded;
7. downgrade, rollback, and compatibility paths work;
8. documentation and examples execute automatically.

All programs remain available for parallel development and research regardless
of another program's integration status.
