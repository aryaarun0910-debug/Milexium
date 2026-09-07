# Intelligence-layer build backlog

This file turns the research radar into concrete software-first projects that can later move into accelerators.

## Tier 1: feasible for a small technical team

| Project concept | Research inputs | First product | Hardware path | Key proof point |
|---|---|---|---|---|
| Verified code-agent context engine | Type slicing, Lean/Pantograph, SWE-RL | IDE/agent service that returns minimal causal context and executable verification plans | Incremental provenance graph engine on FPGA/DPU only after fleet scale | Fewer regressions and lower token/context cost on real repositories |
| Adaptive memory runtime | TTT, MemoryLLM, Doc-to-LoRA, Mem-alpha | Versioned per-user memory with update evaluation and rollback | CXL-attached memory service or smart NIC for adapter/cache management | Better long-horizon task success at fixed latency and privacy budget |
| Agent environment and verifier fabric | OpenEnv, Atropos, Agent World Model | Standard SDK for executable tasks, rewards, snapshots and replay | DPU-isolated sandbox execution and CPU verifier appliances | Higher GPU utilisation and reproducible cross-framework RL runs |
| Evolutionary kernel laboratory | OpenEvolve, ShinkaEvolve, Triton/MLIR | Agent that evolves kernels against real hardware counters with correctness tests | FPGA/ASIC design-space exploration and generated accelerator IP | Repeated end-to-end wins across devices, not a single benchmark |
| Scientific equation discovery workbench | LLM-SR, SR4MDL, Lean | Domain-aware equation search with units, invariants and proof/fit checks | Symbolic-search accelerator or batched FPGA evaluator later | Rediscovery of held-out laws and robust extrapolation |
| Private local research OS | autoresearch, DeepScientist, Panda | Local experiment graph, result memory and multi-runner orchestration | Workstation appliance with GPU scheduling and encrypted persistent memory | More validated improvements per compute pound than manual baselines |

## Tier 2: venture-scale software infrastructure

1. **Adaptive inference control plane:** schedule decode, retrieval, memory writes, LoRA generation, test-time updates and rollback across model replicas.
2. **Verifier cloud:** secure execution of tests, theorem provers, numerical simulations and database constraints as reward endpoints.
3. **Embodied experience exchange:** standardised datasets, simulations, policy checkpoints and replay traces across robot embodiments.
4. **AI-for-science compiler:** domain IR for equivariant graphs, neighbour lists, FFT operators, diffusion sampling and differentiable simulation.
5. **Formal knowledge foundry:** convert papers, code and informal mathematics into typed definitions, statements, proofs and executable counterexample generators.

## Tier 3: hardware moonshots

- **Fast-weight and adapter accelerator:** SRAM/HBM engine for low-rank updates, versioned parameter deltas and rapid tenant switching.
- **Verifier DPU:** isolated processor for tests, proofs, policy checks, trace capture and deterministic replay beside GPU clusters.
- **World-model rollout ASIC:** low-precision recurrent/latent dynamics engine for millions of imagined trajectories per second.
- **Geometric scientific accelerator:** tensor-product, neighbour-list and equivariant message-passing dataflow for chemistry and materials models.
- **Symbolic search FPGA fabric:** reconfigurable evaluation of expression trees, constraints, SAT/SMT propagators and exact arithmetic.

## Suggested 90-day programme

### Days 1-30: reproduce and instrument
Choose one project from three different layers. Reproduce a published result, add end-to-end profiling and record bytes moved, verifier cost, rollout variance, failure modes and dependency/licence constraints.

### Days 31-60: build a shared substrate
Create a common event log and evaluator API so experiments from all three projects produce comparable trajectories, costs and certificates. The goal is not another agent UI; it is reusable measurement infrastructure.

### Days 61-90: demonstrate compounding leverage
Run a closed loop in which the system proposes a change, evaluates it, stores the result, updates its policy or memory, and performs better on a held-out distribution. Report negative results and evaluator exploits explicitly.
