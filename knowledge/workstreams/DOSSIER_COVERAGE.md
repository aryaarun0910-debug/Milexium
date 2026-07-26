# Dossier coverage ledger (live)

Traceability for the source ledger at `blueprint/20-dossier-coverage-ledger.md`
in the expansion plan (`C:\Users\aryaa\Documents\Milexium Expansion plan`).
That file records the *intended* landing point for all 80 software-to-silicon
technologies and 72 intelligence-layer projects; this file records *actual*
implementation status in this repository, using the exact vocabulary from
`knowledge/architecture/decisions/0001-...md`: **Exists**, **Specified**,
**Demonstrated**, **Validated**, **Production**.

**Status as of 2026-07-23 (expansion kickoff):** every one of the 152 entries
below is **Specified** — a landing point and program are recorded, but the
specific technology itself has no code in this repository. Two programs (A —
canonical substrate, in `app/canonical`; G — verify, in `app/verify`)
now have a first versioned contract (v0.1) that a future implementation of a
landing-point entry would build against; that is noted per-row as "A/G
foundation exists" where applicable, but it is **not** the same as the
technology itself existing. Do not read "foundation exists" as partial credit
for the technology — it means the wall the technology would eventually be
built against is no longer blank.

Update this file's **Status** column (only) as work lands; do not edit the
**Technology**/**Program**/**Landing point** columns without an ADR, since
those mirror the normative blueprint.

## Methodology note

This ledger is large by design — it is the whole dossier. Rather than
one-line-editing 152 rows by hand every session, treat "Status" as the field
a work packet updates when (and only when) it actually implements, benchmarks,
or vendors the specific technology in that row — not when it touches the
Program the row happens to land in.

## All 80 software-to-silicon technologies

| # | Technology | Program | Milexium landing point | Status | Note |
|---:|---|---|---|---|---|
| 1 | DPUs and SmartNICs | K/L | Verifier sandboxes, tenant isolation, telemetry, storage and crypto offload | Specified | No implementation yet |
| 2 | Distributed inference scheduling and expert/cache placement | D/J/K | Route models, adapters, caches, rollouts, and verifiers across heterogeneous workers | Specified | No implementation yet |
| 3 | Filtered and hybrid ANN execution | C/I/K | Tenant/policy/time/geography-constrained semantic case retrieval | Specified | `SemanticIndex` protocol + `ExactSearchIndex` exist (app/canonical/semantic_index.py) as the bounded-quality reference this would extend; filtering/hybrid execution itself not built |
| 4 | KV-cache compression and quantization | D/J/K | Larger agent/research context and higher inference concurrency | Specified | No implementation yet |
| 5 | Trusted execution and confidential computing | L | Attested processing of operator data, models, and private analytics | Specified | No implementation yet |
| 6 | TurboQuant and TurboVec | C/K | Compressed online semantic-state index and packed search kernels | Specified | Explicitly not vendored yet — knowledge/architecture/decisions/0005-semantic-index-interface.md requires a dedicated license/security/maturity ADR first |
| 7 | CHERI capability systems and memory-safe embedded stacks | L | Capability-scoped plugins, parsers, edge runtime, and accelerator control | Specified | No implementation yet |
| 8 | CIRCT hardware compiler infrastructure | G/K | Verified lowering from Execution IR into FPGA/ASIC representations | Specified | A/G foundation exists (app/verify v0.1); CIRCT itself not touched |
| 9 | CXL memory pooling and fabric management | C/D/K | Tier embeddings, case memory, simulation state, and parameter deltas | Specified | No implementation yet |
| 10 | Compiler-driven kernel fusion and tensor compilers | E/H/K | Remove intermediate traffic in forecast, graph, simulation, and AI kernels | Specified | No implementation yet |
| 11 | Computational storage | C/K | Near-data filtering, decompression, feature scans, and vector search | Specified | No implementation yet |
| 12 | DiskANN and SSD-native graph search | C/K | Large cold/warm semantic memory beyond DRAM | Specified | No implementation yet |
| 13 | Fully homomorphic encryption | L | Narrow encrypted counts, scoring, and aggregate comparisons | Specified | No implementation yet |
| 14 | GPU and parallel branch-and-bound | F/K | Batched routing/scheduling bounds, nodes, neighborhoods, and scenarios | Specified | No implementation yet |
| 15 | Low-bit AI quantization: INT4, FP8 and FP4 | D/E/J/K | Efficient model, agent, and edge execution with task-quality contracts | Specified | No implementation yet |
| 16 | MLIR multi-level intermediate representation | K | Milexium Execution IR dialects and progressive multi-target lowering | Specified | No implementation yet |
| 17 | Sparse Mixture-of-Experts routing | D/J/K | Domain specialists for schemas, policy, forecasting, optimization, and evidence | Specified | No implementation yet |
| 18 | Sparse tensor algebra compilation (TACO-class) | E/H/K | Sparse road, graph, feature, and simulation kernels | Specified | No implementation yet |
| 19 | Speculative decoding | D/I/J/K | Faster evidence synthesis, policy analysis, and agent execution | Specified | No implementation yet |
| 20 | TVM, MetaSchedule and hardware-native tensor IR | E/H/K | Auto-tuned transport model and simulation kernels | Specified | No implementation yet |
| 21 | Triton and Gluon-style GPU kernel DSLs | E/F/H/K | Custom GPU kernels for scoring, bounds, graphs, and ensembles | Specified | No implementation yet |
| 22 | Zero-knowledge proof systems and proof accelerators | G/L | Selective proof of execution, compliance, integrity, or aggregates | Specified | A/G foundation exists (app/verify v0.1: schema/state/hash-chain verifiers); ZK proofs not touched |
| 23 | eBPF and XDP programmable datapaths | K/L | Runtime observability, network policy, lineage, and enforcement | Specified | No implementation yet |
| 24 | Compiler-managed compute/communication overlap | D/E/J/K | Hide checkpoint, collective, simulation, and rollout movement | Specified | No implementation yet |
| 25 | PagedAttention and continuous-batching inference runtimes | D/J/K | Efficient multi-agent and operator-copilot serving | Specified | No implementation yet |
| 26 | CP-SAT and lazy-clause-generation constraint solving | F/G | Scheduling/recovery backend with learned conflicts and certificates | Specified | A/G foundation exists; CP-SAT integration not built (roadmap's OR-Tools scheduler work is tracked separately in knowledge/docs/MASTER_ROADMAP.md, not this ledger) |
| 27 | Equality saturation and e-graphs | A/F/G/K | Rewrite policies, constraint expressions, queries, and kernels under cost models | Specified | A/G foundation exists; e-graph rewriting not built |
| 28 | Learning-guided combinatorial optimisation | F/J | Learn solver selection, warm starts, branching, and neighborhoods from traces | Specified | No implementation yet |
| 29 | Solver-aided programming | A/F/G/K | Synthesize mappings, policies, encodings, counterexamples, and kernels | Specified | A/G foundation exists; synthesis itself not built |
| 30 | Chisel and parameterized RTL generators | K | Configurable retrieval, filtering, verification, and simulation accelerators | Specified | No implementation yet |
| 31 | Compressed sensing and sparse recovery | B/E/K/L | Sparse telemetry and edge measurement with explicit recovery assumptions | Specified | No implementation yet |
| 32 | Processing-in-memory and near-memory computing | C/K | Bandwidth-bound scans, graph operations, retrieval, and feature aggregation | Specified | No implementation yet |
| 33 | RISC-V custom instruction extensions | K/L | Packed scoring, bitmap, sketch, crypto, and constraint-propagation primitives | Specified | No implementation yet |
| 34 | Randomized numerical linear algebra and graph sparsification | E/F/H/K | Compress matrices, road graphs, scenarios, and relaxations with error bounds | Specified | No implementation yet |
| 35 | SMT solving | A/F/G | State/policy verification, counterexamples, and solver backend | **Exists** | z3 wired in for **state verification** (ADR-0033): `knowledge/architecture/formal/` proves 5 invariants — ServiceRequest lifecycle S1–S4 + hash-chain tamper-evidence H1 — run by `app/verify/formal.py`, 10 tests, z3 in CI. NOT yet used as a Program F *solver backend*, and no counterexample extraction surface |
| 36 | Succinct data structures and FM-indexes | C/I/K | Compressed exact event, route, policy, and evidence lookup | Specified | No implementation yet |
| 37 | Systolic and dataflow accelerator generators | E/H/K | Regular graph, tensor, dynamic-programming, and simulation pipelines | Specified | No implementation yet |
| 38 | High-level synthesis (HLS) | K | Transport-domain kernels compiled into FPGA/ASIC implementations | Specified | No implementation yet |
| 39 | MILP branch-and-cut | F | Mixed discrete/continuous scheduling, allocation, and policy optimization | Specified | No implementation yet |
| 40 | Secure multiparty computation, PIR and ORAM | C/L | Cross-agency analytics and private precedent retrieval | Specified | No implementation yet |
| 41 | Anisotropic vector quantization and ScaNN | C/K | Alternative high-recall semantic retrieval backend | Specified | `SemanticIndex` protocol exists as the interface this would implement; ScaNN itself not vendored |
| 42 | CGRA compilers and FPGA overlays | K | Reconfigurable substrate for recurring transport kernels | Specified | No implementation yet |
| 43 | DaCe data-centric compilation | E/H/K | Explicit data movement for models, replay, and simulations | Specified | No implementation yet |
| 44 | Dynamic FPGA partial reconfiguration | G/K/L | Load signed verifier, retrieval, and simulation hardware functions | Specified | A/G foundation exists; FPGA path not touched |
| 45 | FlashAttention and IO-aware exact attention | D/J/K | Efficient long-context operator and research-agent inference | Specified | No implementation yet |
| 46 | Selective state-space and scan-based sequence models | D/E/H/K | Operational event, telemetry, and long-horizon sequence modeling | Specified | No implementation yet |
| 47 | CDCL SAT solving | F/G | Boolean policy, configuration, planning, and proof-log backend | Specified | A/G foundation exists; no SAT solver wired in |
| 48 | Automatic-differentiation compilers | E/H/K | Differentiable twins, inverse calibration, sensitivity, and control | Specified | No implementation yet |
| 49 | Product quantization and asymmetric distance computation | C/K | Benchmark and alternative compressed vector representation | Specified | `SemanticIndex` protocol exists as the interface this would implement | 
| 50 | DPDK and userspace kernel bypass | B/K | High-rate ingestion, replay, and private network datapaths | Specified | No implementation yet |
| 51 | Roaring and bit-sliced indexes | C/I/K | Exact filters, ACLs, cohort operations, and block skipping | Specified | No implementation yet |
| 52 | GPUDirect RDMA and direct storage | E/H/J/K | Direct movement of batches, simulations, embeddings, and checkpoints | Specified | No implementation yet |
| 53 | Structured sparsity | D/E/K | Hardware-compatible pruning and sparse execution | Specified | No implementation yet |
| 54 | Topology-aware collective communication | D/E/J/K | Efficient distributed model, rollout, and simulation collectives | Specified | No implementation yet |
| 55 | Approximation algorithms, PTAS and primal-dual methods | F | Fast certified-quality routing, allocation, and network solutions | Specified | No implementation yet |
| 56 | Fixed-parameter algorithms and kernelization | F | Reduce disruption, conflict, vehicle-class, and separator structure | Specified | No implementation yet |
| 57 | Proof-carrying code and certified optimisation | G/K/L | Certificates on plugins, kernels, policies, and decision artifacts | Specified | A/G foundation exists; no proof-carrying artifacts yet |
| 58 | Superoptimization | G/K | Verified optimization of compact scoring, bitmap, crypto, and solver kernels | Specified | A/G foundation exists; not touched |
| 59 | Syntax-guided synthesis (SyGuS) | A/B/F/G/K | Grammar-constrained generation of mappings, rules, expressions, and code | Specified | A/G foundation exists; SyGuS not built |
| 60 | io_uring and zero-copy asynchronous I/O | B/C/J/K | Efficient ingestion, artifact, environment, and storage pipelines | Specified | No implementation yet |
| 61 | Verified compilers | G/K/L | Certified toolchains for critical edge and accelerator software | Specified | A/G foundation exists; not touched |
| 62 | CUDA Graphs and captured execution | E/H/J/K | Repeated forecast, simulation, verifier, and rollout workflows | Specified | No implementation yet |
| 63 | Halide-style separation of algorithm and schedule | E/H/K | Retarget stable transport algorithms across hardware schedules | Specified | No implementation yet |
| 64 | NVMe-over-Fabrics and storage disaggregation | C/J/K | Elastic dataset, artifact, vector, and experiment storage | Specified | No implementation yet |
| 65 | Polyhedral compilation | E/H/K | Affine loop transformations for regular numerical pipelines | Specified | No implementation yet |
| 66 | Streaming sketches: Count-Min, HyperLogLog and quantile sketches | B/C/E/K | Live frequency, cardinality, quantile, drift, and heavy-hitter monitoring | Specified | No implementation yet |
| 67 | Translation validation | G/K | Validate every compiler/IR optimization against its source semantics | Specified | A/G foundation exists (the "independent verifier re-derives, does not trust" pattern in app/verify is the same principle) |
| 68 | ZeRO and fully sharded data parallelism | D/E/J/K | Distributed training of models, agents, and world models | Specified | No implementation yet |
| 69 | Learned index structures | C/K | Stable high-volume temporal and analytical lookup with exact fallback | Specified | No implementation yet |
| 70 | Polymorphic type slicing | B/G/I/J | Minimal mapping, proof, explanation, and code-agent context | Specified | A/G foundation exists; not touched |
| 71 | QUBO, Ising formulations and annealing | F/K | Alternative backend for compatible binary subproblems | Specified | No implementation yet |
| 72 | Incremental and self-adjusting computation | A/B/C/E/F/H | Change-proportional imports, features, forecasts, decisions, and simulations | Specified | A foundation exists (app/canonical); incremental recomputation itself not built |
| 73 | MaxSAT and pseudo-Boolean optimisation | F/G | Weighted policy, configuration, coverage, and scheduling problems | Specified | A/G foundation exists; not touched |
| 74 | Partial evaluation and multi-stage programming | A/F/K | Tenant/service specialization of policy, schema, query, and kernel logic | Specified | A foundation exists; not touched |
| 75 | Locality-sensitive hashing | C/K | Streaming/predictable-recall retrieval benchmark and backend | Specified | `SemanticIndex` protocol exists as the interface this would implement |
| 76 | Graph DSLs and graph-specific compilation | E/F/H/K | Road, service, demand, dependency, and knowledge graph execution | Specified | No implementation yet |
| 77 | Cuckoo and XOR filters | B/C/K | Deduplication, negative lookup, cache admission, and integrity checks | Specified | Content-addressed raw objects (app/estate, sha256 names) give exact dedup detection; probabilistic filters themselves not built |
| 78 | HNSW navigable small-world graphs | C/K | Dynamic ANN backend and benchmark comparator | Specified | `SemanticIndex` protocol exists as the interface this would implement |
| 79 | Interactive theorem proving and proof extraction | A/G | Machine-checked state, policy, compiler, and decision knowledge | Specified (partial) | Automated SMT proofs now exist (row 35, ADR-0033) — machine-checked state invariants, no longer only a manual precursor. But this row is *interactive* theorem proving (Lean/Coq/Isabelle) with proof **extraction**: not started, and z3 emits no extractable proof term |
| 80 | RDMA and RoCE | C/D/J/K | Low-copy distributed state, model, rollout, and storage transport | Specified | No implementation yet |

## All 72 intelligence-layer projects

Grouped exactly as in `blueprint/20-dossier-coverage-ledger.md`. All entries
are **Specified** as of 2026-07-23 -- none of these projects have landed in
this repository; the table below exists so a future packet can flip a row's
status without re-deriving the mapping from the source blueprint.

### Adaptive memory and test-time learning

| Project | Product | Status |
|---|---|---|
| TTT-LM | Core | Specified |
| In-Place TTT | Core/Runtime | Specified |
| TTRL | Forge/Core | Specified |
| TTT-Discover | Forge | Specified |
| MemoryLLM / M+ | Core | Specified |
| MLP Memory | Core | Specified |
| MemoryDecoder | Core | Specified |
| Mem-alpha | Core/Forge | Specified |
| FreqKV | Runtime | Specified |
| VQKV | Runtime | Specified |
| Doc-to-LoRA | Core | Specified |
| PENCIL | Core/Explain | Specified |

### Reasoning, reinforcement learning, and agent training

| Project | Product | Status |
|---|---|---|
| Open-R1 | Forge | Specified |
| Open-Reasoner-Zero | Forge | Specified |
| TinyZero | Forge | Specified |
| veRL | Forge/Fabric | Specified |
| rLLM | Forge/Fabric | Specified |
| OpenRLHF | Forge | Specified |
| Atropos | Fabric | Specified |
| SWE-RL | Forge | Specified |
| Open-AgentRL | Forge/Fabric | Specified |
| OpenEnv | Fabric | Specified |
| Agent World Model | Fabric | Specified |
| Agent0 | Forge | Specified |

### Self-improving software and autonomous research

| Project | Product | Status |
|---|---|---|
| SICA | Forge | Specified |
| Darwin Gödel Machine | Forge | Specified |
| OpenEvolve | Forge/Runtime | Specified |
| ShinkaEvolve | Forge | Specified |
| autoresearch | Forge | Specified |
| AI Scientist v2 | Forge | Specified |
| Panda | Forge | Specified |
| OpenAGS | Forge | Specified |
| AFlow | Forge | Specified |
| Tencent SelfEvolvingAgent | Forge | Specified |
| Agent Laboratory | Forge | Specified |
| DeepScientist | Forge | Specified |

### Formal reasoning and machine-assisted discovery

| Project | Product | Status |
|---|---|---|
| Lean 4 | Verify | Specified -- app/verify v0.1 exists but uses plain Python, not Lean; a real Lean integration is unstarted |
| mathlib4 | Verify | Specified |
| LeanDojo v2 | Verify/Forge | Specified |
| LeanCopilot | Verify | Specified |
| Pantograph | Verify/Fabric | Specified |
| Goedel-Prover | Verify | Specified |
| DeepSeek-Prover V1.5 | Verify/Forge | Specified |
| LeanProgress | Verify/Forge | Specified |
| LLM-SR | Forecast/Forge | Specified |
| LLM-SRBench | Forecast/Benchmark | Specified |
| SR4MDL | Forecast/Forge | Specified |
| TorchLean | Verify/Runtime | Specified |

### AI for science and differentiable simulation

| Project | Product | Status |
|---|---|---|
| MatterGen | Forge/Simulation | Specified |
| Boltz | Core/Runtime | Specified |
| Chai-1 | Core | Specified |
| OpenFold | Forge/Runtime | Specified |
| DiffDock | Decide/Simulation | Specified |
| RFdiffusion | Decide/Simulation | Specified |
| MACE | Simulation/Runtime | Specified |
| Open Catalyst Project | Benchmark/Forge | Specified |
| NeuralGCM | Forecast/Simulation | Specified |
| GraphCast | Forecast/Runtime | Specified |
| FourCastNet | Forecast/Runtime | Specified |
| JAX-MD | Simulation/Runtime | Specified |

### World models, embodied intelligence, and robotics

| Project | Product | Status |
|---|---|---|
| V-JEPA 2 | Simulation/Core | Specified |
| DreamerV3 | Simulation/Forge | Specified |
| TD-MPC2 | Decide/Simulation | Specified |
| OpenVLA | Edge/Core | Specified |
| LeRobot | Edge/Fabric | Specified |
| Octo | Edge/Core | Specified |
| Open X-Embodiment | Fabric/Data | Specified |
| Diffusion Policy | Decide/Edge | Specified |
| ManiSkill | Simulation/Fabric | Specified |
| Genesis | Simulation/Fabric | Specified |
| Isaac Lab | Simulation/Edge | Specified |
| Habitat-Lab | Simulation/Forge | Specified |

## Coverage summary

- **Exists:** 0 / 152 — no dossier *technology* is itself implemented. Several
  now have real foundations they would build on (Programs A, B, C, D, G, I
  have v0.1 slices; the `SemanticIndex` interface + `ExactSearchIndex`
  reference exists for the ANN-family rows 3/41/49/75/78; content-addressed
  estate storage exists for the dedup/integrity rows 77), but a foundation is
  not the technology — these stay Specified until the specific technology
  lands and clears `_legacy/third_party/VENDORING_PROCESS.md`.
- **Specified:** 152 / 152.
- **Demonstrated / Validated / Production:** 0 / 152.

Deliberate non-movement: the strategic direction (transport decision runtime
others integrate; independent evidence from public data) is served by the
canonical/decision/evidence contracts, the standards adapters, the SDK/API
surface, and the governed data estate — **not** by vendoring dossier
technologies. `blueprint/15-risks-and-falsification.md`'s first strategic risk
is "infrastructure before demand"; bulk-vendoring FPGA/FHE/world-model
toolchains now would be exactly that. The estate + vendoring gate
(`_legacy/third_party/VENDORING_PROCESS.md`) exist so the *next* technology can land
deliberately (pgvector and OR-Tools are the nearest candidates), not so this
count can be inflated.
