# Software-to-silicon intelligence architecture

## Purpose

This document translates the complete software-to-silicon dossier into
Milexium's transport intelligence architecture. It assumes parallel execution
capacity and defines the full system rather than a calendar-limited subset.

The central design is a closed, verifiable learning loop:

```text
Connect -> Canonical State -> Predict -> Decide -> Verify -> Simulate/Execute
   ^                                                        |
   |                                                        v
Standards <- Promote <- Evaluate <- Learn <- Retain Experience
```

The loop is useful only when every promoted improvement retains its data,
version, cost, verifier result, outcome, and rollback target.

## Expanded Milexium product system

| Product | Responsibility | Scientific and systems differentiation |
|---|---|---|
| **Milexium Connect** | Ingest vendor exports, feeds, policies, telemetry, and standards | Schema inference, semantic-loss analysis, incremental computation, provenance slicing |
| **MilexiumDB** | Canonical bitemporal operational state and outcome memory | State-machine primitives, event sourcing, compressed projections, workload-aware storage |
| **Milexium Core** | Company-wide task, model, feature, and memory runtime | Adaptive memory, model routing, calibrated uncertainty, online learning with rollback |
| **Milexium Forecast** | Demand, duration, cancellation, congestion, and risk distributions | Hierarchical Bayes, conformal prediction, state-space models, graph/spectral surrogates |
| **Milexium Decide** | Scheduling, recovery, allocation, negotiation, and policy optimization | CP-SAT/MILP/SMT portfolios, decomposition, learning-guided search, certified approximation |
| **Milexium Verify** | Independent feasibility, policy, proof, test, and quality checking | Verifier fabric, proof-carrying decisions, formal models, executable invariants |
| **Milexium Replay** | Historical reconstruction, counterfactual simulation, and incident analysis | Bitemporal replay, discrete-event digital twins, causal evaluation, scenario worlds |
| **Milexium Explain** | Causal context, alternatives, evidence, and operator-facing rationale | Provenance/type slicing, minimal explanation graphs, semantic precedent retrieval |
| **Milexium Forge** | Autonomous research, benchmark, code, model, solver, and policy evolution | Experiment DAGs, evolutionary search, agent environments, holdout evaluators |
| **Milexium Fabric** | Events, experience, evaluators, sandboxes, artifacts, and distributed execution | OpenEnv-style ABI, immutable traces, heterogeneous scheduling, verifier queues |
| **Milexium Runtime** | Hardware-aware execution and data movement | Cost models, kernel selection, quantization, sketches, direct I/O, CPU/GPU/DPU/FPGA backends |
| **Milexium Edge** | Vehicle, depot, facility, and private-site execution | Offline state, signed policy bundles, streaming inference, confidential and memory-safe deployment |

## Five proprietary intermediate representations

Milexium should own representations that preserve domain meaning until the last
responsible lowering step.

### Transport State IR

Typed entities, bitemporal facts, state transitions, external identities,
lineage, corrections, sensitivity, and validity. It lowers into relational
tables, event envelopes, columnar snapshots, graph projections, and semantic
case documents.

### Decision IR

Variables, domains, hard constraints, soft constraints, lexicographic and Pareto
objectives, uncertainty sets, freeze horizons, incumbent solutions, explanation
labels, and certificate requirements. It lowers into CP-SAT, MILP, SMT, MaxSAT,
heuristics, GPU search, or future accelerator kernels.

### Evidence IR

Claims, sources, information cutoffs, transformation chains, alternatives,
verifier outputs, proof objects, uncertainty, approvals, outcomes, and
counterexamples. It lowers into API objects, case files, reports, attestations,
Lean/TLA+ obligations, and machine-verifiable manifests.

### Experience IR

Environment, initial state, action trace, tool calls, costs, reward components,
verifier results, outcome, failure taxonomy, and retained lesson. It is the
common substrate for operator learning, solver learning, agent RL, simulations,
and autonomous research.

### Execution IR

Logical kernels, shapes, sparsity, precision, layouts, memory tiers, allowable
error, target hardware, and validation function. It lowers through MLIR/Triton,
native Rust/C++, CUDA, eBPF, FPGA/HLS, or accelerator-specific backends.

Each lowering emits a versioned artifact and a validator. Optimization may
change representation and execution, but it may not silently change meaning.

## Intelligence loop

### Propose

Models, solvers, operators, agents, and evolutionary programs generate candidate
forecasts, schedules, interventions, mappings, policies, kernels, and research
hypotheses.

### Verify

Milexium Verify routes each candidate through the applicable combination of:

- schema and type checks;
- relational and temporal invariants;
- policy guards and authorization;
- independent solution feasibility;
- exact reference implementations;
- property-based and metamorphic tests;
- simulator and replay checks;
- statistical coverage and calibration checks;
- SMT, TLA+, Lean, or proof-certificate checking;
- security and tenant-isolation checks;
- hardware numerical-tolerance and translation validation.

### Evaluate

The evaluator records correctness, service quality, equity, stability, cost,
latency, memory, energy proxy, data movement, operator burden, and downstream
outcomes. Metrics are multi-objective rather than collapsed prematurely.

### Retain

Successful and unsuccessful attempts enter the experience store. Memory
formation produces:

- exact structured facts;
- semantic decision episodes;
- solver traces and learned branching features;
- failure exemplars and counterexamples;
- policy precedents and overrides;
- parameter deltas or adapters;
- cost-model observations;
- optimized kernels and proof artifacts.

### Improve

Forge uses retained experience to propose new candidates. Promotion remains
external to the proposal agent: signed evaluation policy decides whether a
candidate becomes a challenger, canary, champion, or rejected artifact.

## Complete 80-technology translation

The dossier's entire technology portfolio maps into seven Milexium programs.

### Compiler intelligence and verification: technologies 8, 16, 27, 29, 48,
57, 58, 59, 61, 65, 67, 70, 72, 74, and 79

| Dossier technologies | Milexium integration |
|---|---|
| MLIR and CIRCT | Foundation for Execution IR, progressive lowering, accelerator contracts, and future RTL generation |
| Equality saturation/e-graphs | Optimize constraint expressions, policy predicates, evidence queries, feature DAGs, and kernels against measured cost models |
| Solver-aided programming, SyGuS, and superoptimization | Synthesize policy rules, constraint encodings, field mappings, verifier plans, and hot microkernels |
| Verified compilers, translation validation, proof-carrying code, theorem proving | Validate every aggressive lowering and attach machine-checkable certificates to deployable artifacts |
| Polymorphic type/provenance slicing | Produce minimal causal context for explanations, schema errors, agent edits, and evidence requests |
| Incremental computation and partial evaluation | Recompute only affected forecasts/decisions and specialize policies, schemas, and kernels per tenant or service |
| Polyhedral and automatic-differentiation compilers | Optimize regular simulation/forecast kernels and differentiate digital twins or surrogate models |

### Heterogeneous compilation and hardware generation: technologies 1, 11, 18,
20, 21, 30, 32, 33, 37, 38, 42, 43, 44, 63, and 76

| Dossier technologies | Milexium integration |
|---|---|
| TVM, Triton, DaCe, TACO, Halide, Graph DSLs | Generate transport-specific dense, sparse, graph, raster, and streaming kernels |
| Chisel, HLS, CIRCT, systolic generators | Produce verified accelerator prototypes for scoring, filtering, simulation, and solver bounds |
| RISC-V extensions and CGRA/FPGA overlays | Define portable primitives for packed vector scoring, bitmap filtering, sketches, and constraint propagation |
| Partial FPGA reconfiguration | Load signed workload-specific kernels for retrieval, verification, routing, or simulation |
| Processing/near-memory and computational storage | Execute scans, filters, decompression, semantic search, and feature aggregation where the bytes reside |
| DPUs/SmartNICs | Isolate tenants, execute verifier sandboxes, enforce network policy, capture traces, and offload storage/crypto work |

### Datacenter and data movement: technologies 9, 23, 24, 49, 50, 52, 54, 60,
62, 64, and 68

| Dossier technologies | Milexium integration |
|---|---|
| CXL memory pooling | Tier embeddings, case memory, KV caches, and simulation state by measured hotness |
| eBPF/XDP | Observe and enforce data-plane provenance, latency, tenant boundaries, and service policy |
| DPDK, io_uring, zero copy | High-throughput ingestion, replay, artifact serving, and index generation |
| RDMA, GPUDirect, NVMe-oF | Move columnar batches, embeddings, checkpoints, and simulation state without redundant host copies |
| CUDA Graphs | Capture recurring forecast, feature, simulation, and verification graphs |
| Topology-aware collectives, ZeRO/FSDP, compute/communication overlap | Train and serve distributed forecasting, graph, world, and reasoning models efficiently |

### Retrieval and mathematical compression: technologies 3, 6, 12, 31, 34,
36, 41, 51, 66, 69, 75, 77, 78, and 80

| Dossier technologies | Milexium integration |
|---|---|
| TurboQuant/TurboVec, PQ, ScaNN, HNSW, LSH, DiskANN | A portfolio-selected semantic state index across RAM and SSD tiers |
| Filtered ANN and Roaring/bit-sliced indexes | Tenant-, policy-, geography-, service-, and time-constrained retrieval inside the execution path |
| Succinct indexes and learned indexes | Compressed event, route, policy, and temporal lookup with exact fallback |
| Cuckoo/XOR filters | Deduplication, negative lookup, cache admission, and replay manifest checks |
| Streaming sketches | Live cardinality, frequency, latency, quantile, drift, and heavy-hitter telemetry with explicit error bounds |
| Randomized linear algebra and graph sparsification | Compress feature matrices, travel networks, scenario ensembles, and optimization relaxations |
| Compressed sensing | Sparse telemetry and edge-sensor acquisition where measurement cost is binding |

### AI execution and model systems: technologies 2, 4, 10, 15, 17, 19, 25,
45, 46, and 53

| Dossier technologies | Milexium integration |
|---|---|
| FlashAttention, PagedAttention, speculative decoding | Efficient operator copilot, evidence synthesis, policy analysis, and agent-swarm inference |
| KV compression, low-bit quantization, structured sparsity | Larger private context, more concurrent agents, lower inference memory and cost |
| Selective state-space models | Long operational sequences, event streams, vehicle telemetry, and bounded-state edge inference |
| Sparse MoE | Specialists for schemas, policies, optimization, forecasting, security, and explanation |
| Distributed inference scheduling | Route models, adapters, caches, verifiers, and environments across heterogeneous resources |
| Compiler kernel fusion | Eliminate intermediate data movement in forecasting, graph, retrieval, and simulation pipelines |

### NP and combinatorial optimization: technologies 14, 26, 28, 35, 39, 47,
55, 56, 71, and 73

| Dossier technologies | Milexium integration |
|---|---|
| CP-SAT, MILP, SMT, SAT, MaxSAT/pseudo-Boolean | Solver portfolio for scheduling, assignment, policy validation, configuration, and counterexamples |
| GPU/parallel branch-and-bound | Batch bounds, neighborhoods, scenarios, and homogeneous subproblems while retaining certificates |
| Learning-guided optimization | Learn warm starts, branching, neighborhood selection, and solver routing from retained traces |
| Approximation/primal-dual | Fast solutions with explicit quality contracts for large online instances |
| Fixed-parameter methods/kernelization | Detect small disruption sets, conflict graphs, vehicle classes, or geographic separators and reduce instances |
| QUBO/Ising/annealing | Alternative backend for selected binary subproblems under the same Decision IR and verifier |

### Private, verifiable, and memory-safe computing: technologies 5, 7, 13, 22,
and 40

| Dossier technologies | Milexium integration |
|---|---|
| Confidential computing/TEEs | Attested processing of operator exports, models, and cross-organization analyses |
| FHE | Encrypted narrow computations such as counts, risk scoring, or aggregate comparisons |
| MPC/PIR/ORAM | Cross-agency benchmarking, private precedent retrieval, and clean-room analytics |
| Zero-knowledge proofs | Prove execution, policy compliance, aggregate claims, or artifact integrity without revealing sensitive inputs |
| CHERI and memory-safe Rust | Capability-scoped plugins, edge runtimes, parsers, and accelerator control planes |

## Complete 72-project intelligence-layer translation

### Adaptive memory and test-time learning

TTT-LM, In-Place TTT, TTRL, TTT-Discover, MemoryLLM/M+, MLP Memory,
MemoryDecoder, Mem-alpha, FreqKV, VQKV, Doc-to-LoRA, and PENCIL inform
**Milexium Adaptive Memory**:

- exact facts remain in canonical state;
- semantic cases live in retrieval memory;
- operational sequences may use learned memory/state;
- tenant-specific adapters become versioned knowledge cartridges;
- test-time changes run as isolated deltas;
- every delta has an origin, evaluator, expiry, rollback, and leakage boundary;
- cognitive-workspace compaction retains dependencies so deleted context can be
  reconstructed or challenged.

### Reasoning, reinforcement learning, and agent training

Open-R1, Open-Reasoner-Zero, TinyZero, veRL, rLLM, OpenRLHF, Atropos, SWE-RL,
Open-AgentRL, OpenEnv, Agent World Model, and Agent0 inform **Milexium
Experience Fabric**:

- an environment ABI exposes reset, observe, act, verify, snapshot, restore, and
  replay;
- transport environments include databases, feeds, policy tools, solvers,
  simulators, incident injectors, and operator-response models;
- reward is a signed vector of feasibility, KPI, equity, stability, cost,
  evidence quality, and safety—not one opaque scalar;
- curricula are generated from real failure clusters and held-out perturbations;
- model workers remain separate from CPU/database/simulator verifier workers.

### Self-improving software and autonomous research

SICA, Darwin Gödel Machine, OpenEvolve, ShinkaEvolve, autoresearch, AI Scientist
v2, Panda, OpenAGS, AFlow, Tencent SelfEvolvingAgent, Agent Laboratory, and
DeepScientist inform **Milexium Forge**:

- agents may mutate code, models, solver encodings, heuristics, schemas,
  policies, prompts, tests, and kernels;
- a population/archive preserves diversity instead of replacing everything with
  the current winner;
- experiment graphs record hypotheses, parents, diffs, environments, cost, and
  evaluator outputs;
- hidden test sets, adversarial environments, and independent replication block
  evaluator overfitting;
- promotion authority is isolated from mutation authority.

### Formal reasoning and machine-assisted discovery

Lean 4, mathlib4, LeanDojo v2, LeanCopilot, Pantograph, Goedel-Prover,
DeepSeek-Prover V1.5, LeanProgress, LLM-SR, LLM-SRBench, SR4MDL, and TorchLean
inform **Milexium Formal Knowledge**:

- formalize transport state and decision invariants;
- generate and check counterexamples for policies and solver encodings;
- attach proof obligations to compiler and runtime transformations;
- discover compact symbolic demand, congestion, travel-time, or cancellation
  relationships subject to units and known invariants;
- use neural systems for premise/tactic/equation proposals while small trusted
  checkers validate results.

### AI for science and differentiable simulation

MatterGen, Boltz, Chai-1, OpenFold, DiffDock, RFdiffusion, MACE, Open Catalyst,
NeuralGCM, GraphCast, FourCastNet, and JAX-MD supply transferable patterns for
**Milexium Scientific Transport Models**:

- conditional generation followed by external validation becomes scenario and
  schedule generation followed by a feasibility/evidence verifier;
- equivariance becomes invariance to identifier relabeling and appropriate
  geographic/temporal transformations;
- hybrid physical/learned modeling becomes known fleet/road/queue dynamics plus
  learned residuals;
- graph and Fourier surrogates enable fast network-wide forecasts and ensembles;
- differentiable simulation supports inverse calibration, sensitivity, and
  policy optimization;
- minimum-description-length symbolic discovery creates inspectable laws rather
  than prediction-only models.

The biological/material models themselves are not transplanted into transport;
their architecture patterns, evaluation loops, and compiler primitives are.

### World models, embodied intelligence, and robotics

V-JEPA 2, DreamerV3, TD-MPC2, OpenVLA, LeRobot, Octo, Open X-Embodiment,
Diffusion Policy, ManiSkill, Genesis, Isaac Lab, and Habitat-Lab inform
**Milexium World and Edge Models**:

- learn latent operational dynamics from event, map, fleet, and facility
  sequences;
- imagine disruption trajectories before selecting recovery actions;
- standardize cross-fleet/cross-agency trajectory formats;
- generate large synthetic experience sets in vectorized digital twins;
- use model-predictive control for bounded advisory horizons;
- run quantized policies and safety monitors on vehicles, depots, or facilities;
- preserve explicit operational constraints around every learned action.

## Cross-product integrations

| Capability | Connect | DB | Forecast | Decide | Explain/Replay | Forge/Runtime |
|---|---|---|---|---|---|---|
| Provenance slicing | Field derivations | Fact lineage | Feature lineage | Constraint cause | Minimal evidence | Agent context |
| Adaptive memory | Mapping precedents | Case memory | Regime memory | Solver trace memory | Operator precedents | Adapter/delta evolution |
| Verifier fabric | Schema checks | Invariants | Calibration | Feasibility | Replay integrity | Promotion checks |
| World models | Feed environments | State trajectories | Latent dynamics | Imagined rollouts | Counterfactual worlds | Synthetic curriculum |
| Formal methods | Mapping contracts | State safety | Task contracts | Policy proofs | Claim proofs | Translation validation |
| Hardware-aware IR | Parsers | Storage formats | Tensor/graph kernels | Solver kernels | Simulation kernels | Backend selection |
| Privacy compute | Clean-room ingest | Protected state | Private training | Confidential optimization | Selective disclosure | Attested experiments |

## Compounding moat

The defensible asset is the joined corpus of:

- canonical transport meanings and semantic-loss mappings;
- bitemporal operational and outcome histories;
- policy and constraint libraries;
- independent verifier suites and counterexamples;
- solver traces, warm starts, and instance fingerprints;
- operator overrides and evidence precedents;
- simulation environments and calibrated world models;
- model, adapter, and memory-delta evaluations;
- hardware counters, execution schedules, and cost models;
- formal specifications, proofs, and translation validators.

Open-source components can be replaced. This connected experience/proof/cost
graph compounds only through Milexium's integrated operation.
