# Open-source intelligence-layer research radar

**Research cut-off:** 23 July 2026  
**Scope:** 72 open-source research projects that can increase the memory, reasoning, learning, verification, discovery or embodied capability of software systems.

This extension deliberately excludes ordinary application wrappers. A project is included when it exposes a new learning loop, representation, verifier, environment, scientific model or systems substrate that could compound intelligence over repeated use. Repository maturity and licensing should be rechecked before commercial adoption.

## Executive synthesis

The emerging intelligence stack is becoming a closed loop: **experience generation -> memory formation -> test-time adaptation -> search/reasoning -> executable verification -> scientific or physical action -> retained improvement**. The hardware implication is that future AI systems will need more than matrix engines. They will need low-latency parameter-delta application, persistent memory tiers, rollout and simulator farms, proof/checker services, secure sandboxes, experiment databases and schedulers that continuously move work between CPUs, GPUs, DPUs, FPGAs and storage.

### Highest-leverage themes

| Theme | Strategic interpretation | Likely hardware pressure |
|---|---|---|
| Runtime learning | Models update from the current problem or user rather than waiting for retraining | Fast low-rank updates, versioned state, rollback, tenant isolation |
| Verifier-rich RL | Exact tests, theorem provers, simulators and database checks turn experience into reliable rewards | CPU verifier farms, async queues, secure execution, GPU saturation |
| Autonomous experiment loops | Agents modify code, launch experiments and retain improvements | Sandbox fleets, provenance stores, cost-aware search, accelerator benchmarking |
| Formalised knowledge | Proof objects and typed libraries make generated reasoning machine-checkable | Retrieval plus tactic generation on GPUs, small trusted kernels on CPUs |
| Scientific generative models | Candidate molecules, materials, equations and controls are proposed then externally validated | Equivariant kernels, simulation, FFT/graph workloads, lab/DFT queues |
| Embodied world models | Learned latent dynamics and massive simulation provide synthetic experience | GPU physics/rendering, edge inference, streaming sensor and memory systems |

## Top 20 projects for strategic diligence

| Rank | Project | Category | Score / 5 | Why it matters |
|---:|---|---|---:|---|
| 1 | [AI Scientist v2](https://github.com/SakanaAI/AI-Scientist-v2) | Self-improving software and autonomous research | 4.9 | Expands the unit of automation from a code task to an entire research programme with explicit branching and experiment management. |
| 2 | [Lean 4](https://github.com/leanprover/lean4) | Formal reasoning and machine-assisted discovery | 4.9 | Provides a machine-checkable substrate for mathematical knowledge, software specifications and proof-producing agents. |
| 3 | [mathlib4](https://github.com/leanprover-community/mathlib4) | Formal reasoning and machine-assisted discovery | 4.9 | Acts as structured, verified training data and a compositional knowledge base for theorem-proving systems. |
| 4 | [MatterGen](https://github.com/microsoft/mattergen) | AI for science and differentiable simulation | 4.9 | Transforms materials search into conditional generation followed by physical/ML validation. |
| 5 | [Boltz](https://github.com/jwohlwend/boltz) | AI for science and differentiable simulation | 4.9 | A fully open stack enables both scientific inspection and vertical drug-discovery products instead of API-only access. |
| 6 | [V-JEPA 2](https://github.com/facebookresearch/vjepa2) | World models, embodied intelligence and robotics | 4.9 | Predictive latent representations may form a world-model layer that is cheaper and more action-relevant than generative video. |
| 7 | [LeRobot](https://github.com/huggingface/lerobot) | World models, embodied intelligence and robotics | 4.9 | The most important contribution may be standardisation: common data and hardware interfaces allow intelligence to compound across robots. |
| 8 | [Open X-Embodiment](https://github.com/google-deepmind/open_x_embodiment) | World models, embodied intelligence and robotics | 4.9 | Data interoperability is an intelligence multiplier: it enables larger policies, cross-robot transfer and comparable evaluation. |
| 9 | [TTT-LM](https://github.com/test-time-training/ttt-lm-jax) | Adaptive memory and test-time learning | 4.8 | Turns context processing into online learning rather than passive attention; the software opportunity is a runtime that decides what to learn, when to update, and how to roll back harmful updates. |
| 10 | [TTRL](https://github.com/PRIME-RL/TTRL) | Adaptive memory and test-time learning | 4.8 | Suggests inference can generate experience and then use that experience to update the model. |
| 11 | [Doc-to-LoRA](https://github.com/SakanaAI/doc-to-lora) | Adaptive memory and test-time learning | 4.8 | Collapses retrieval context into a compact weight delta. |
| 12 | [veRL](https://github.com/volcengine/verl) | Reasoning, reinforcement learning and agent training | 4.8 | Potentially becomes the control plane for experience-based model improvement: rollouts, rewards, policy updates and agentic environments. |
| 13 | [SWE-RL](https://github.com/facebookresearch/swe-rl) | Reasoning, reinforcement learning and agent training | 4.8 | Transforms repositories, diffs and test outcomes into an experience stream. |
| 14 | [OpenEnv](https://github.com/meta-pytorch/OpenEnv) | Reasoning, reinforcement learning and agent training | 4.8 | Could become an ABI for agent experience, analogous to what Gym did for classic RL but with richer tools, databases and sandboxes. |
| 15 | [Agent World Model](https://github.com/Snowflake-Labs/agent-world-model) | Reasoning, reinforcement learning and agent training | 4.8 | Environment generation tackles a central bottleneck: agents need abundant interactive experience, not only static text. |
| 16 | [Darwin Gödel Machine](https://github.com/jennyzzt/dgm) | Self-improving software and autonomous research | 4.8 | Combines self-reference with evolutionary archives rather than requiring every new version to descend from only the current best. |
| 17 | [OpenEvolve](https://github.com/algorithmicsuperintelligence/openevolve) | Self-improving software and autonomous research | 4.8 | Makes algorithm and implementation search accessible as a reusable open framework. |
| 18 | [ShinkaEvolve](https://github.com/SakanaAI/ShinkaEvolve) | Self-improving software and autonomous research | 4.8 | Focuses on maintaining diversity and extracting more value per expensive evaluation, a critical issue in real scientific search. |
| 19 | [LeanDojo v2](https://github.com/lean-dojo/LeanDojo-v2) | Formal reasoning and machine-assisted discovery | 4.8 | Bridges formal libraries and machine learning with reproducible environments and interfaces. |
| 20 | [Goedel-Prover](https://github.com/Goedel-LM/Goedel-Prover) | Formal reasoning and machine-assisted discovery | 4.8 | Combines formalisation and proof generation, attacking both the translation bottleneck and proof search. |


## Adaptive memory and test-time learning

### TTT-LM

- **Repository:** [https://github.com/test-time-training/ttt-lm-jax](https://github.com/test-time-training/ttt-lm-jax)
- **Novelty:** Makes an RNN hidden state a learnable model and updates it with self-supervised gradient steps while processing the test sequence.
- **Intelligence-layer leverage:** Turns context processing into online learning rather than passive attention; the software opportunity is a runtime that decides what to learn, when to update, and how to roll back harmful updates.
- **Software-to-hardware path:** Linear-time recurrent execution, but with training-like inner loops. Strong targets include fused update kernels, SRAM-resident fast weights, FPGA streaming pipelines and accelerators that combine inference and low-rank weight updates.
- **P/NP lens:** P/probabilistic: each update is polynomial; stability, selection of updates and long-horizon credit remain empirical.
- **Maturity:** Research implementation; high scientific novelty, medium product readiness
- **Strategic score:** **4.8/5**

### In-Place TTT

- **Repository:** [https://github.com/ByteDance-Seed/In-Place-TTT](https://github.com/ByteDance-Seed/In-Place-TTT)
- **Novelty:** Adds test-time training to existing transformer LLMs through a drop-in training, conversion, inference and evaluation stack.
- **Intelligence-layer leverage:** Important because it reduces the architecture-change barrier: runtime adaptation can become a serving feature rather than requiring an entirely new model family.
- **Software-to-hardware path:** Requires fast parameter-delta management, isolation between users, checkpointing, mixed-precision update kernels and scheduling between decode and adaptation.
- **P/NP lens:** P/probabilistic; the central risk is non-stationary behaviour and unsafe adaptation, not worst-case complexity.
- **Maturity:** Research stack; promising bridge to deployable adaptive inference
- **Strategic score:** **4.7/5**

### TTRL

- **Repository:** [https://github.com/PRIME-RL/TTRL](https://github.com/PRIME-RL/TTRL)
- **Novelty:** Uses test-time reinforcement learning on unlabeled data, deriving reward signals from test-time scaling behaviours such as consensus.
- **Intelligence-layer leverage:** Suggests inference can generate experience and then use that experience to update the model. This is a genuine intelligence-layer loop: propose, evaluate, learn, retry.
- **Software-to-hardware path:** Rollout generation, verifier aggregation and online optimisation create a new datacenter workload combining inference clusters, reward services and short-burst training.
- **P/NP lens:** NP/heuristic at the outer reasoning-search level; the RL update itself is polynomial stochastic optimisation. No complexity-class shortcut is implied.
- **Maturity:** Active research code with reproducible scripts; high upside and high safety/variance risk
- **Strategic score:** **4.8/5**

### TTT-Discover

- **Repository:** [https://github.com/test-time-training/discover](https://github.com/test-time-training/discover)
- **Novelty:** Applies reinforcement learning at test time so a model can acquire problem-specific experience while attempting a discovery task.
- **Intelligence-layer leverage:** Moves from “think longer” to “learn from attempts.” The valuable software layer is experiment memory, reward construction and adaptive compute allocation per problem.
- **Software-to-hardware path:** Maps to asynchronous rollout engines, batched evaluators, simulator accelerators and high-bandwidth parameter-update paths.
- **P/NP lens:** Often attacks hard search spaces heuristically; improvements are instance-level and do not alter NP-hard worst cases.
- **Maturity:** Early research project; strategically important but not yet a stable platform
- **Strategic score:** **4.7/5**

### MemoryLLM / M+

- **Repository:** [https://github.com/wangyu-ustc/MemoryLLM](https://github.com/wangyu-ustc/MemoryLLM)
- **Novelty:** Adds an updatable memory component to a language model and extends it toward scalable long-term memory.
- **Intelligence-layer leverage:** Treats memory as model state rather than only retrieved text. This could support low-latency personalisation, continual knowledge updates and private on-device memory.
- **Software-to-hardware path:** Memory modules may be sharded, quantised or placed on CXL/SSD tiers; write-heavy memory operations create opportunities for near-memory compute and persistent accelerator state.
- **P/NP lens:** P/probabilistic; retrieval/update policy quality is empirical and continual-learning interference is the core risk.
- **Maturity:** Research code and checkpoints; medium maturity
- **Strategic score:** **4.5/5**

### MLP Memory

- **Repository:** [https://github.com/LUMIA-Group/MLPMemory](https://github.com/LUMIA-Group/MLPMemory)
- **Novelty:** Uses a retriever-pretrained MLP as an external neural memory for language models.
- **Intelligence-layer leverage:** Interesting middle ground between symbolic retrieval and fully modifying the base model: a learned memory can be independently trained, updated and served.
- **Software-to-hardware path:** Dense MLP lookup/update operations can be placed on separate memory accelerators, smart NICs or CXL-attached devices; compression and batching determine economics.
- **P/NP lens:** P/probabilistic; approximate retrieval and learned generalisation rather than exact database semantics.
- **Maturity:** ICLR-era research implementation; early but concrete
- **Strategic score:** **4.4/5**

### MemoryDecoder

- **Repository:** [https://github.com/LUMIA-Group/MemoryDecoder](https://github.com/LUMIA-Group/MemoryDecoder)
- **Novelty:** Provides a pretrained plug-and-play memory decoder intended to augment an existing LLM.
- **Intelligence-layer leverage:** Decouples memory capacity from the core model and may create a standard memory interface across model vendors.
- **Software-to-hardware path:** Potential hardware path is an independent memory-serving card or DPU with compressed keys, decoder kernels and tenant isolation.
- **P/NP lens:** P/probabilistic; latency, forgetting and contamination are operational issues.
- **Maturity:** Research implementation with reusable components
- **Strategic score:** **4.3/5**

### Mem-alpha

- **Repository:** [https://github.com/wangyu-ustc/Mem-alpha](https://github.com/wangyu-ustc/Mem-alpha)
- **Novelty:** Learns how to construct agent memory using reinforcement learning rather than fixed summarisation rules.
- **Intelligence-layer leverage:** Memory formation becomes a trainable policy. This is more valuable than another vector store because it addresses what should be retained and in what representation.
- **Software-to-hardware path:** The hot path is trajectory collection, memory scoring, compression and retrieval; accelerators could support streaming summarisation and hierarchical stores.
- **P/NP lens:** NP/heuristic selection problem in practice; RL learns a policy without guaranteeing globally optimal memory.
- **Maturity:** Early research code; high conceptual leverage
- **Strategic score:** **4.5/5**

### FreqKV

- **Repository:** [https://github.com/LUMIA-Group/FreqKV](https://github.com/LUMIA-Group/FreqKV)
- **Novelty:** Compresses transformer key-value caches in the frequency domain to extend context windows.
- **Intelligence-layer leverage:** Shows that cache representations can exploit signal structure rather than using uniform token eviction or scalar quantisation.
- **Software-to-hardware path:** Natural targets are fused FFT/DCT-like transforms, low-bit cache formats, HBM controllers and inference runtimes that schedule compressed and exact cache tiers.
- **P/NP lens:** P-approximate: explicit quality/latency trade-off; no hard-search claim.
- **Maturity:** Research implementation; relatively close to systems integration
- **Strategic score:** **4.4/5**

### VQKV

- **Repository:** [https://github.com/LUMIA-Group/VQKV](https://github.com/LUMIA-Group/VQKV)
- **Novelty:** Applies vector quantisation to key-value caches for high compression with improved fidelity.
- **Intelligence-layer leverage:** KV cache is a rapidly growing serving cost. Learned or structured codebooks create a software wedge that can later become cache-specific silicon.
- **Software-to-hardware path:** Maps directly to lookup-table scoring, bit-packed memory, vector instructions and HBM bandwidth reduction.
- **P/NP lens:** P-approximate with measurable reconstruction and task-quality error.
- **Maturity:** Research implementation; attractive near-term systems opportunity
- **Strategic score:** **4.6/5**

### Doc-to-LoRA

- **Repository:** [https://github.com/SakanaAI/doc-to-lora](https://github.com/SakanaAI/doc-to-lora)
- **Novelty:** Uses a hypernetwork to convert document context into LoRA-style parameter updates that internalise facts quickly.
- **Intelligence-layer leverage:** Collapses retrieval context into a compact weight delta. It could create portable, cacheable “knowledge cartridges” for models and agents.
- **Software-to-hardware path:** Requires fast hypernetwork inference, delta loading, multiplexed adapter memory and secure per-tenant parameter state. FPGA or DPU adapter managers are plausible.
- **P/NP lens:** P/probabilistic; generated updates are approximate and require validation against hallucination or interference.
- **Maturity:** ICML 2026 research implementation with weights; high novelty
- **Strategic score:** **4.8/5**

### PENCIL

- **Repository:** [https://github.com/chr26195/pencil](https://github.com/chr26195/pencil)
- **Novelty:** Generates long chains of thought with a small context window by recursively deleting intermediate thoughts no longer needed.
- **Intelligence-layer leverage:** Treats reasoning memory as garbage-collected state. The broader idea is an operating system for cognitive workspace, not simply a longer context window.
- **Software-to-hardware path:** Hardware leverage comes from lower KV traffic and from runtime support for state compaction, dependency tracking and selective recomputation.
- **P/NP lens:** P/heuristic; determining what can be safely discarded is an approximate relevance problem.
- **Maturity:** Early research implementation; strong systems idea
- **Strategic score:** **4.4/5**

## Reasoning, reinforcement learning and agent training

### Open-R1

- **Repository:** [https://github.com/huggingface/open-r1](https://github.com/huggingface/open-r1)
- **Novelty:** A fully open effort to reproduce reasoning-model training recipes, including data, supervised fine-tuning and reinforcement learning.
- **Intelligence-layer leverage:** Lowers the barrier to experimenting with reward design and reasoning traces, making the training stack itself an extensible intelligence layer.
- **Software-to-hardware path:** Large-scale rollout, reward verification and distributed optimisation favour tightly integrated inference/training clusters and specialised verifier services.
- **P/NP lens:** NP/heuristic reasoning search layered on polynomial training kernels.
- **Maturity:** Mature open research ecosystem; strong platform value
- **Strategic score:** **4.7/5**

### Open-Reasoner-Zero

- **Repository:** [https://github.com/Open-Reasoner-Zero/Open-Reasoner-Zero](https://github.com/Open-Reasoner-Zero/Open-Reasoner-Zero)
- **Novelty:** Open implementation of large-scale reasoning-oriented reinforcement learning from a base model.
- **Intelligence-layer leverage:** Useful because it exposes the recipe, parameters, data and weights needed to study emergent verification and search behaviours.
- **Software-to-hardware path:** Same hardware pattern as RLHF but more rollout-heavy: inference throughput, long sequences, reward checks and checkpoint churn dominate.
- **P/NP lens:** Hard reasoning tasks remain hard; RL changes the search policy and practical success distribution.
- **Maturity:** Research platform with released assets
- **Strategic score:** **4.6/5**

### TinyZero

- **Repository:** [https://github.com/Jiayi-Pan/TinyZero](https://github.com/Jiayi-Pan/TinyZero)
- **Novelty:** Minimal reproduction showing small models can develop verification/search behaviours through reinforcement learning on constrained tasks.
- **Intelligence-layer leverage:** A compact test bed for studying which parts of reasoning emergence require scale and which come from environment and reward structure.
- **Software-to-hardware path:** Excellent FPGA/small-cluster research target because experiments are small enough to profile end-to-end and co-design rollout plus update hardware.
- **P/NP lens:** Structured task environments; no general NP breakthrough.
- **Maturity:** Educational/research implementation; original repo is largely superseded by veRL
- **Strategic score:** **4.0/5**

### veRL

- **Repository:** [https://github.com/volcengine/verl](https://github.com/volcengine/verl)
- **Novelty:** Distributed reinforcement-learning framework for LLMs with flexible training and inference backends.
- **Intelligence-layer leverage:** Potentially becomes the control plane for experience-based model improvement: rollouts, rewards, policy updates and agentic environments.
- **Software-to-hardware path:** Strong datacenter leverage: disaggregated inference/training, sequence parallelism, checkpoint movement, network topology and GPU utilisation.
- **P/NP lens:** P stochastic optimisation with heuristic policy search.
- **Maturity:** Fast-moving infrastructure project; high practical relevance
- **Strategic score:** **4.8/5**

### rLLM

- **Repository:** [https://github.com/rllm-org/rllm](https://github.com/rllm-org/rllm)
- **Novelty:** Framework for training agents with reinforcement learning while integrating with multiple agent frameworks and benchmark environments.
- **Intelligence-layer leverage:** Makes agent behaviour rather than isolated text generation the trainable object.
- **Software-to-hardware path:** Needs trace capture, asynchronous experience queues, reward execution and multi-GPU optimisation; DPUs can isolate environments and telemetry.
- **P/NP lens:** Agent planning may be combinatorial; RL supplies heuristics and policies.
- **Maturity:** Emerging framework; promising interoperability
- **Strategic score:** **4.5/5**

### OpenRLHF

- **Repository:** [https://github.com/OpenRLHF/OpenRLHF](https://github.com/OpenRLHF/OpenRLHF)
- **Novelty:** Open distributed RLHF and reinforcement-learning stack for large models.
- **Intelligence-layer leverage:** Provides reusable infrastructure beneath many reasoning and alignment experiments, reducing the cost of testing new algorithms.
- **Software-to-hardware path:** Datacenter-scale scheduling, ZeRO/FSDP, inference engines and high-speed collectives are the main hardware interfaces.
- **P/NP lens:** P stochastic optimisation; reward optimisation does not guarantee global behavioural properties.
- **Maturity:** Established open-source training stack
- **Strategic score:** **4.4/5**

### Atropos

- **Repository:** [https://github.com/NousResearch/atropos](https://github.com/NousResearch/atropos)
- **Novelty:** Environment microservice framework for asynchronous reinforcement learning with language models.
- **Intelligence-layer leverage:** Separates environments from trainers through a trajectory interface, enabling a marketplace of executable learning tasks.
- **Software-to-hardware path:** Environment services can run on CPU pools, simulators, browsers or accelerators while GPUs remain saturated with generation/training.
- **P/NP lens:** Often wraps hard interactive tasks; reward and policy learning are heuristic.
- **Maturity:** Active and community-oriented; strong intelligence-infrastructure thesis
- **Strategic score:** **4.7/5**

### SWE-RL

- **Repository:** [https://github.com/facebookresearch/swe-rl](https://github.com/facebookresearch/swe-rl)
- **Novelty:** Uses open software-evolution data and rule-based rewards to train language models for real software engineering.
- **Intelligence-layer leverage:** Transforms repositories, diffs and test outcomes into an experience stream. This can compound with every open-source change and every customer codebase.
- **Software-to-hardware path:** Requires sandbox fleets, incremental builds, test execution and diff evaluators; CPUs and storage can dominate more than GPU FLOPs.
- **P/NP lens:** Software repair is combinatorial and program correctness is undecidable in general; tests provide partial verifiers.
- **Maturity:** NeurIPS 2025 research code; strategically important
- **Strategic score:** **4.8/5**

### Open-AgentRL

- **Repository:** [https://github.com/Gen-Verse/Open-AgentRL](https://github.com/Gen-Verse/Open-AgentRL)
- **Novelty:** General agentic RL framework spanning terminal, GUI, software engineering and tool-use settings.
- **Intelligence-layer leverage:** Attempts to optimise multiple components of an agent in a closed loop rather than training only the base model.
- **Software-to-hardware path:** Calls for heterogeneous clusters: GPUs for policy models, CPU/browser farms for environments, storage for traces and fast networking for asynchronous feedback.
- **P/NP lens:** Heuristic optimisation over long-horizon tasks; no global guarantees.
- **Maturity:** ICML 2026-stage research project; high ambition
- **Strategic score:** **4.6/5**

### OpenEnv

- **Repository:** [https://github.com/meta-pytorch/OpenEnv](https://github.com/meta-pytorch/OpenEnv)
- **Novelty:** Standard interface for isolated agentic execution environments using Gym-style APIs and deployable packaging.
- **Intelligence-layer leverage:** Could become an ABI for agent experience, analogous to what Gym did for classic RL but with richer tools, databases and sandboxes.
- **Software-to-hardware path:** Strong DPU/virtualisation opportunity: secure environment execution, network policy, snapshotting and deterministic replay.
- **P/NP lens:** The environment API is P infrastructure; tasks inside may be arbitrarily hard.
- **Maturity:** Active ecosystem infrastructure with broad integrations
- **Strategic score:** **4.8/5**

### Agent World Model

- **Repository:** [https://github.com/Snowflake-Labs/agent-world-model](https://github.com/Snowflake-Labs/agent-world-model)
- **Novelty:** Synthesises executable SQL-backed tool-use environments for large-scale multi-turn agentic reinforcement learning.
- **Intelligence-layer leverage:** Environment generation tackles a central bottleneck: agents need abundant interactive experience, not only static text.
- **Software-to-hardware path:** Database-backed environments, verification and MCP services can scale horizontally on CPU/storage clusters while GPU workers train policies.
- **P/NP lens:** Generating useful curricula is heuristic; task execution is mostly polynomial database/program work.
- **Maturity:** ICML 2026 research release with datasets and environments
- **Strategic score:** **4.8/5**

### Agent0

- **Repository:** [https://github.com/aiming-lab/Agent0](https://github.com/aiming-lab/Agent0)
- **Novelty:** Self-evolving agents from zero curated data using a curriculum agent and an executor agent that co-evolve through tool-integrated reasoning.
- **Intelligence-layer leverage:** The important novelty is automatic curriculum creation: the system generates its own frontier rather than waiting for human datasets.
- **Software-to-hardware path:** Compute shifts toward large volumes of verified rollouts, tool execution and curriculum filtering. Efficient schedulers and verifier accelerators matter.
- **P/NP lens:** Open-ended search is heuristic and potentially unbounded; gains are empirical.
- **Maturity:** Early research release; high upside and high evaluation risk
- **Strategic score:** **4.7/5**

## Self-improving software and autonomous research

### SICA

- **Repository:** [https://github.com/MaximeRobeyns/self_improving_coding_agent](https://github.com/MaximeRobeyns/self_improving_coding_agent)
- **Novelty:** A coding agent repeatedly evaluates itself, modifies its own codebase and retains changes that improve benchmark performance.
- **Intelligence-layer leverage:** A clean experimental substrate for recursive software improvement with an explicit archive and evaluation loop.
- **Software-to-hardware path:** Sandboxed build/test farms, benchmark caching and code-diff execution dominate. Hardware acceleration is secondary until many parallel variants are evaluated.
- **P/NP lens:** Program search is enormous and generally intractable; evolutionary/agent search is heuristic and benchmark-bound.
- **Maturity:** Research prototype; useful for controlled experiments
- **Strategic score:** **4.5/5**

### Darwin Gödel Machine

- **Repository:** [https://github.com/jennyzzt/dgm](https://github.com/jennyzzt/dgm)
- **Novelty:** Open-ended system that modifies its own agent code and empirically validates changes on coding benchmarks.
- **Intelligence-layer leverage:** Combines self-reference with evolutionary archives rather than requiring every new version to descend from only the current best.
- **Software-to-hardware path:** Scales through parallel sandboxes, evaluation caching and heterogeneous model calls; secure execution is essential.
- **P/NP lens:** Heuristic search over programs; empirical improvement does not imply formal self-correctness.
- **Maturity:** Research code; conceptually significant and operationally risky
- **Strategic score:** **4.8/5**

### OpenEvolve

- **Repository:** [https://github.com/algorithmicsuperintelligence/openevolve](https://github.com/algorithmicsuperintelligence/openevolve)
- **Novelty:** Evolutionary coding agent inspired by AlphaEvolve, using language models to mutate and optimise programs against measurable objectives.
- **Intelligence-layer leverage:** Makes algorithm and implementation search accessible as a reusable open framework. The moat opportunity is evaluator libraries and workload-specific archives.
- **Software-to-hardware path:** Ideal for hardware co-design: generated kernels can be benchmarked on GPUs, CPUs, FPGAs or simulators; evaluation parallelism is the key resource.
- **P/NP lens:** Heuristic program synthesis over NP-hard/undecidable spaces; correctness must come from tests or proofs.
- **Maturity:** Active community project; high practical experimentation value
- **Strategic score:** **4.8/5**

### ShinkaEvolve

- **Repository:** [https://github.com/SakanaAI/ShinkaEvolve](https://github.com/SakanaAI/ShinkaEvolve)
- **Novelty:** Open-ended, sample-efficient program evolution framework aimed at scientific discovery and optimisation.
- **Intelligence-layer leverage:** Focuses on maintaining diversity and extracting more value per expensive evaluation, a critical issue in real scientific search.
- **Software-to-hardware path:** Works well with distributed experiment schedulers, GPU kernel benchmarks, simulators and lab automation.
- **P/NP lens:** Heuristic evolutionary search; can attack NP-hard design spaces without changing worst-case complexity.
- **Maturity:** 2026 active research release; strong discovery platform candidate
- **Strategic score:** **4.8/5**

### autoresearch

- **Repository:** [https://github.com/karpathy/autoresearch](https://github.com/karpathy/autoresearch)
- **Novelty:** Lets an agent repeatedly modify a compact language-model training codebase, run short experiments and keep improvements.
- **Intelligence-layer leverage:** A minimal example of “research organisation as code”: the human writes the research constitution and the agent executes the experimental loop.
- **Software-to-hardware path:** Single-GPU baseline, but naturally scales to experiment fleets, scheduler-aware early stopping and shared result memory.
- **P/NP lens:** Heuristic search over training programs and hyperparameters.
- **Maturity:** Compact experimental project; high educational and cultural influence
- **Strategic score:** **4.6/5**

### AI Scientist v2

- **Repository:** [https://github.com/SakanaAI/AI-Scientist-v2](https://github.com/SakanaAI/AI-Scientist-v2)
- **Novelty:** End-to-end scientific research system using agentic tree search to generate hypotheses, run experiments, analyse results and draft papers.
- **Intelligence-layer leverage:** Expands the unit of automation from a code task to an entire research programme with explicit branching and experiment management.
- **Software-to-hardware path:** Requires sandboxed GPU experiments, literature retrieval, plotting, LaTeX and tree-search scheduling. Secure execution and cost-aware pruning are core infrastructure.
- **P/NP lens:** Research planning and experiment selection are combinatorial and heuristic; peer acceptance is not equivalent to truth.
- **Maturity:** Advanced research prototype with real artefacts; requires stringent oversight
- **Strategic score:** **4.9/5**

### Panda

- **Repository:** [https://github.com/allenai/panda](https://github.com/allenai/panda)
- **Novelty:** Plan-and-act autonomous research agent with an outer planning loop and inner act-reflect loop.
- **Intelligence-layer leverage:** Provides a general controller specialised through research tools and prompts; useful as a transparent baseline for autonomous discovery systems.
- **Software-to-hardware path:** CPU-heavy tools, retrieval and experimental code execution surround model inference. Traceability and replay are more important than raw decode speed.
- **P/NP lens:** Heuristic planning over open-ended action spaces.
- **Maturity:** Active research agent; moderate maturity
- **Strategic score:** **4.3/5**

### OpenAGS

- **Repository:** [https://github.com/openags/auto-research-ui](https://github.com/openags/auto-research-ui)
- **Novelty:** Open framework for multi-agent autonomous research from literature review through hypothesis generation, experiments and manuscript production.
- **Intelligence-layer leverage:** Treats scientific work as a collaborative agent workflow and provides a user-facing research operating environment.
- **Software-to-hardware path:** Opportunity lies in workflow orchestration, provenance stores, sandboxing, multi-model routing and local/private execution.
- **P/NP lens:** Heuristic orchestration; scientific validity still requires independent replication.
- **Maturity:** Fast-moving open-source product/research hybrid
- **Strategic score:** **4.2/5**

### AFlow

- **Repository:** [https://github.com/FoundationAgents/AFlow](https://github.com/FoundationAgents/AFlow)
- **Novelty:** Automatically generates and optimises agent workflows using Monte Carlo tree search over code-represented workflows.
- **Intelligence-layer leverage:** Moves agent engineering from hand-written prompts and graphs toward automated architecture search.
- **Software-to-hardware path:** Workflow evaluation is embarrassingly parallel and can exploit model routers, caching and FPGA/ASIC inference when workloads stabilise.
- **P/NP lens:** MCTS is heuristic search; optimal workflow discovery is combinatorial.
- **Maturity:** ICLR 2025 research implementation; important agent-compiler direction
- **Strategic score:** **4.7/5**

### Tencent SelfEvolvingAgent

- **Repository:** [https://github.com/Tencent/SelfEvolvingAgent](https://github.com/Tencent/SelfEvolvingAgent)
- **Novelty:** Collection of research projects on agents that improve web reasoning, curricula or tool-use behaviour.
- **Intelligence-layer leverage:** Useful as a laboratory for multiple self-evolution mechanisms rather than a single monolithic agent.
- **Software-to-hardware path:** Scales on browser/sandbox fleets and asynchronous trace stores; evaluation quality is the limiting resource.
- **P/NP lens:** Heuristic learning and search.
- **Maturity:** Research collection under active development
- **Strategic score:** **4.2/5**

### Agent Laboratory

- **Repository:** [https://github.com/SamuelSchmidgall/AgentLaboratory](https://github.com/SamuelSchmidgall/AgentLaboratory)
- **Novelty:** End-to-end multi-agent workflow supporting literature review, experimentation and report writing with human involvement.
- **Intelligence-layer leverage:** A practical reference architecture for decomposing scientific work into specialised roles and shared artefacts.
- **Software-to-hardware path:** Local or cloud model serving, literature indexes, sandboxed Python and reproducible project storage are the main systems layers.
- **P/NP lens:** Heuristic planning; no guarantee of novelty or correctness.
- **Maturity:** Usable research workflow with community adoption
- **Strategic score:** **4.2/5**

### DeepScientist

- **Repository:** [https://github.com/ResearAI/DeepScientist](https://github.com/ResearAI/DeepScientist)
- **Novelty:** Local-first autonomous research studio that preserves findings memory, runs iterative experiments and produces paper-oriented outputs.
- **Intelligence-layer leverage:** The local-first and persistent-project design is valuable: intelligence growth depends on durable experimental memory, not isolated chats.
- **Software-to-hardware path:** Maps to workstation/GPU scheduling, experiment databases, Bayesian optimisation and private local models.
- **P/NP lens:** Experiment selection is heuristic; statistical controls are required to avoid overfitting the research loop.
- **Maturity:** Active 2026 project; product-like usability with research ambitions
- **Strategic score:** **4.5/5**

## Formal reasoning and machine-assisted discovery

### Lean 4

- **Repository:** [https://github.com/leanprover/lean4](https://github.com/leanprover/lean4)
- **Novelty:** Programming language and theorem prover with a small trusted kernel and extensible metaprogramming system.
- **Intelligence-layer leverage:** Provides a machine-checkable substrate for mathematical knowledge, software specifications and proof-producing agents.
- **Software-to-hardware path:** Proof checking is highly parallel at the project level; tactic search can use GPUs, while the small kernel remains CPU-friendly and auditable.
- **P/NP lens:** Proof checking is decidable for submitted terms; proof search can be combinatorial or undecidable in broad settings.
- **Maturity:** Mature foundational platform and active ecosystem
- **Strategic score:** **4.9/5**

### mathlib4

- **Repository:** [https://github.com/leanprover-community/mathlib4](https://github.com/leanprover-community/mathlib4)
- **Novelty:** Large collaborative library of formalised mathematics for Lean 4.
- **Intelligence-layer leverage:** Acts as structured, verified training data and a compositional knowledge base for theorem-proving systems.
- **Software-to-hardware path:** Indexing, premise retrieval, incremental builds and distributed checking are the main acceleration opportunities.
- **P/NP lens:** Verification is polynomial in proof-term size under the kernel; discovering proofs remains hard.
- **Maturity:** Large mature community asset
- **Strategic score:** **4.9/5**

### LeanDojo v2

- **Repository:** [https://github.com/lean-dojo/LeanDojo-v2](https://github.com/lean-dojo/LeanDojo-v2)
- **Novelty:** End-to-end framework for extracting data, training, evaluating and deploying AI theorem provers for Lean 4.
- **Intelligence-layer leverage:** Bridges formal libraries and machine learning with reproducible environments and interfaces.
- **Software-to-hardware path:** Supports GPU premise/proof models plus CPU proof checking; retrieval and search scheduling can be independently accelerated.
- **P/NP lens:** Proof search is combinatorial; kernel verification supplies exact certificates.
- **Maturity:** Research infrastructure with strong reuse potential
- **Strategic score:** **4.8/5**

### LeanCopilot

- **Repository:** [https://github.com/lean-dojo/LeanCopilot](https://github.com/lean-dojo/LeanCopilot)
- **Novelty:** Integrates language-model assistance directly into Lean theorem proving.
- **Intelligence-layer leverage:** Shows how neural suggestions can remain subordinate to a trusted formal checker, a strong model for safe code and scientific agents.
- **Software-to-hardware path:** On-device or server inference can propose tactics; the Lean kernel validates them. Quantised small models and retrieval accelerators are natural.
- **P/NP lens:** Heuristic proposal plus exact checking.
- **Maturity:** Usable research tool integrated with Lean
- **Strategic score:** **4.6/5**

### Pantograph

- **Repository:** [https://github.com/leanprover/Pantograph](https://github.com/leanprover/Pantograph)
- **Novelty:** Machine-to-machine interaction system for Lean 4 designed for automated proof agents.
- **Intelligence-layer leverage:** Provides a lower-level control interface than human IDE tooling, enabling tree search, branching and structured proof-state manipulation.
- **Software-to-hardware path:** Search workers can run in parallel while shared proof-state caches and CPU kernels verify candidates.
- **P/NP lens:** Combinatorial proof search with exact certificate checking.
- **Maturity:** Research infrastructure; strategically important interface layer
- **Strategic score:** **4.7/5**

### Goedel-Prover

- **Repository:** [https://github.com/Goedel-LM/Goedel-Prover](https://github.com/Goedel-LM/Goedel-Prover)
- **Novelty:** Open theorem-proving model and data pipeline that formalises natural-language mathematics into Lean and generates proofs.
- **Intelligence-layer leverage:** Combines formalisation and proof generation, attacking both the translation bottleneck and proof search.
- **Software-to-hardware path:** GPU inference and retrieval produce candidate statements/proofs; Lean checking provides a cheap trusted filter.
- **P/NP lens:** Heuristic search with exact proof verification; formalisation correctness still requires semantic review.
- **Maturity:** Open models and code; frontier research
- **Strategic score:** **4.8/5**

### DeepSeek-Prover V1.5

- **Repository:** [https://github.com/deepseek-ai/DeepSeek-Prover-V1.5](https://github.com/deepseek-ai/DeepSeek-Prover-V1.5)
- **Novelty:** Uses proof-assistant feedback, reinforcement learning and Monte Carlo tree search for Lean theorem proving.
- **Intelligence-layer leverage:** Demonstrates a powerful closed loop: generate proof steps, receive exact checker feedback and improve search.
- **Software-to-hardware path:** Long batched proof rollouts, retrieval and CPU checker farms create a heterogeneous acceleration opportunity.
- **P/NP lens:** MCTS/RL tackle hard proof search; accepted proofs are exact certificates.
- **Maturity:** Open research model and code
- **Strategic score:** **4.8/5**

### LeanProgress

- **Repository:** [https://github.com/lean-dojo/LeanProgress](https://github.com/lean-dojo/LeanProgress)
- **Novelty:** Predicts proof progress and uses the signal to guide neural theorem-proving search.
- **Intelligence-layer leverage:** A learned progress metric can reduce wasted search, analogous to value functions in planning.
- **Software-to-hardware path:** Value-model inference can be batched on GPUs; proof states can be cached and verified on CPUs.
- **P/NP lens:** Heuristic guidance over combinatorial search; exact final checking.
- **Maturity:** Minimal research implementation; promising component
- **Strategic score:** **4.5/5**

### LLM-SR

- **Repository:** [https://github.com/deep-symbolic-mathematics/LLM-SR](https://github.com/deep-symbolic-mathematics/LLM-SR)
- **Novelty:** Combines language-model scientific priors, program skeletons and evolutionary search for symbolic equation discovery.
- **Intelligence-layer leverage:** Produces interpretable equations instead of only predictions and can inject domain knowledge into search.
- **Software-to-hardware path:** Candidate evaluation is massively parallel across CPU/GPU simulation; symbolic simplification and constant fitting are accelerator targets.
- **P/NP lens:** Symbolic regression is combinatorial/NP-hard in common formulations; the method is heuristic with empirical validation.
- **Maturity:** ICLR 2025 oral code release
- **Strategic score:** **4.8/5**

### LLM-SRBench

- **Repository:** [https://github.com/deep-symbolic-mathematics/llm-srbench](https://github.com/deep-symbolic-mathematics/llm-srbench)
- **Novelty:** Benchmark of scientific equation discovery designed to test reasoning beyond memorised textbook forms.
- **Intelligence-layer leverage:** Critical because intelligence-layer progress needs adversarial, transformation-based benchmarks rather than easy recycled equations.
- **Software-to-hardware path:** Primarily evaluation infrastructure; scalable candidate execution and symbolic equivalence checking are useful.
- **P/NP lens:** Benchmark spans hard combinatorial search but does not claim complexity reduction.
- **Maturity:** ICML 2025 oral benchmark and open evaluation code
- **Strategic score:** **4.7/5**

### SR4MDL

- **Repository:** [https://github.com/tsinghua-fib-lab/SR4MDL](https://github.com/tsinghua-fib-lab/SR4MDL)
- **Novelty:** Guides symbolic regression using minimum-description-length objectives rather than prediction error alone.
- **Intelligence-layer leverage:** Aligns discovery with compact explanatory laws, reducing overfit equations that merely interpolate data.
- **Software-to-hardware path:** Search and scoring can be distributed; bit-level description-length calculations and symbolic canonicalisation are cheap verification layers.
- **P/NP lens:** Combinatorial search with an information-theoretic objective; heuristic guidance.
- **Maturity:** ICLR 2025 implementation; under continuing development
- **Strategic score:** **4.6/5**

### TorchLean

- **Repository:** [https://github.com/lean-dojo/TorchLean](https://github.com/lean-dojo/TorchLean)
- **Novelty:** Lean framework for neural-network specification, execution and verification.
- **Intelligence-layer leverage:** Connects modern neural computation to formal descriptions, opening paths toward verified kernels, architectures and scientific models.
- **Software-to-hardware path:** Could compile verified network specifications to GPUs/FPGAs while preserving proof obligations and reference semantics.
- **P/NP lens:** Execution is P; verification can involve hard solver obligations but yields certificates.
- **Maturity:** Early 2026 research project; high strategic novelty
- **Strategic score:** **4.7/5**

## AI for science and differentiable simulation

### MatterGen

- **Repository:** [https://github.com/microsoft/mattergen](https://github.com/microsoft/mattergen)
- **Novelty:** Generative model for inorganic materials that can be steered toward chemical, structural and property constraints, with released models and data.
- **Intelligence-layer leverage:** Transforms materials search into conditional generation followed by physical/ML validation. It is a template for closed-loop scientific design.
- **Software-to-hardware path:** GPU diffusion/generative inference, equivariant kernels, relaxation models and DFT queues can form a heterogeneous discovery pipeline.
- **P/NP lens:** Materials design is combinatorial; generation is heuristic and candidates require physical validation.
- **Maturity:** Nature 2025 project with open code, checkpoints and datasets
- **Strategic score:** **4.9/5**

### Boltz

- **Repository:** [https://github.com/jwohlwend/boltz](https://github.com/jwohlwend/boltz)
- **Novelty:** Open family of biomolecular interaction models covering structure and, in later versions, binding-affinity prediction.
- **Intelligence-layer leverage:** A fully open stack enables both scientific inspection and vertical drug-discovery products instead of API-only access.
- **Software-to-hardware path:** Equivariant neural kernels, MSA processing and batched complex inference map strongly to GPUs and specialised geometric accelerators.
- **P/NP lens:** Prediction is polynomial approximate inference; molecular design around it remains combinatorial.
- **Maturity:** High-quality open code and weights; strong translational potential
- **Strategic score:** **4.9/5**

### Chai-1

- **Repository:** [https://github.com/chaidiscovery/chai-lab](https://github.com/chaidiscovery/chai-lab)
- **Novelty:** Multimodal molecular structure-prediction model covering proteins, small molecules, DNA, RNA and modifications.
- **Intelligence-layer leverage:** Unified representation reduces bespoke pipelines across molecular modalities and supports programmable structure workflows.
- **Software-to-hardware path:** Large-memory GPU inference and geometric attention dominate; compilation and lower-precision kernels are direct opportunities.
- **P/NP lens:** Approximate P inference; candidate design and docking search remain hard.
- **Maturity:** Open model package with practical inference tooling
- **Strategic score:** **4.7/5**

### OpenFold

- **Repository:** [https://github.com/aqlaboratory/openfold](https://github.com/aqlaboratory/openfold)
- **Novelty:** Trainable PyTorch reproduction of AlphaFold2 with released training resources and scalable implementation.
- **Intelligence-layer leverage:** Makes protein-folding model internals and retraining accessible, enabling architecture, data and systems research.
- **Software-to-hardware path:** Heavy GPU/accelerator workload with attention, triangle operations, MSA processing and distributed training.
- **P/NP lens:** Approximate polynomial inference; folding’s physical optimisation landscape remains complex.
- **Maturity:** Mature research platform
- **Strategic score:** **4.6/5**

### DiffDock

- **Repository:** [https://github.com/gcorso/DiffDock](https://github.com/gcorso/DiffDock)
- **Novelty:** Diffusion-based generative approach to molecular docking that predicts ligand poses in protein pockets.
- **Intelligence-layer leverage:** Recasts docking from hand-designed search/scoring into learned generative sampling while retaining candidate ranking and physical evaluation.
- **Software-to-hardware path:** Many independent samples make it GPU-parallel; geometric kernels and batched confidence scoring are attractive accelerator targets.
- **P/NP lens:** Docking is hard combinatorial optimisation; diffusion provides a heuristic sampler.
- **Maturity:** Widely used open research implementation
- **Strategic score:** **4.6/5**

### RFdiffusion

- **Repository:** [https://github.com/RosettaCommons/RFdiffusion](https://github.com/RosettaCommons/RFdiffusion)
- **Novelty:** Generative diffusion model for designing protein backbones and structures under constraints.
- **Intelligence-layer leverage:** Moves protein engineering toward programmable generation of structures rather than searching only natural sequence space.
- **Software-to-hardware path:** GPU inference plus downstream sequence design and physical validation; accelerators for equivariant geometry and sampling could reduce iteration time.
- **P/NP lens:** Protein design is combinatorial; generated candidates require experimental validation.
- **Maturity:** Major open research codebase with strong scientific impact
- **Strategic score:** **4.8/5**

### MACE

- **Repository:** [https://github.com/ACEsuit/mace](https://github.com/ACEsuit/mace)
- **Novelty:** Equivariant machine-learning interatomic potentials for accurate atomistic simulation.
- **Intelligence-layer leverage:** Can replace expensive quantum calculations for many simulation steps while retaining geometric inductive bias.
- **Software-to-hardware path:** Excellent GPU/ASIC target: local neighbourhood aggregation, tensor products and repeated force evaluations dominate molecular dynamics.
- **P/NP lens:** P approximate simulation per step; long-horizon sampling and material search remain difficult.
- **Maturity:** Active scientific software with production-facing adoption
- **Strategic score:** **4.7/5**

### Open Catalyst Project

- **Repository:** [https://github.com/Open-Catalyst-Project/ocp](https://github.com/Open-Catalyst-Project/ocp)
- **Novelty:** Open datasets, models and tooling for catalyst discovery using machine learning on atomic structures.
- **Intelligence-layer leverage:** Provides a shared data/model substrate for a high-value scientific domain and encourages reproducible benchmarking.
- **Software-to-hardware path:** Graph neural network training/inference and relaxation loops are GPU-intensive; dataset I/O and distributed evaluation matter.
- **P/NP lens:** Catalyst design is combinatorial; ML ranks and relaxes candidates heuristically.
- **Maturity:** Large established open research ecosystem
- **Strategic score:** **4.7/5**

### NeuralGCM

- **Repository:** [https://github.com/google-research/neuralgcm](https://github.com/google-research/neuralgcm)
- **Novelty:** Hybrid atmospheric model combining differentiable dynamics with learned components.
- **Intelligence-layer leverage:** Represents a powerful pattern: retain known physical structure and learn unresolved or expensive terms.
- **Software-to-hardware path:** Long rollouts, spherical transforms and ensemble forecasts map to accelerators; differentiability enables data assimilation and optimisation.
- **P/NP lens:** P approximate time stepping; uncertainty and chaotic sensitivity dominate rather than NP-hardness.
- **Maturity:** Open research implementation with strong scientific relevance
- **Strategic score:** **4.8/5**

### GraphCast

- **Repository:** [https://github.com/google-deepmind/graphcast](https://github.com/google-deepmind/graphcast)
- **Novelty:** Graph-neural weather forecasting model operating on global meshes.
- **Intelligence-layer leverage:** Demonstrates that learned surrogates can produce fast global forecasts and enable large ensembles.
- **Software-to-hardware path:** Graph message passing, mesh layouts and autoregressive rollouts suit GPU/TPU and potentially graph/dataflow accelerators.
- **P/NP lens:** P approximate inference; weather is chaotic and probabilistic, so calibrated uncertainty is essential.
- **Maturity:** Influential open code and model assets
- **Strategic score:** **4.7/5**

### FourCastNet

- **Repository:** [https://github.com/NVlabs/FourCastNet](https://github.com/NVlabs/FourCastNet)
- **Novelty:** Neural global weather model using Fourier-based operators for high-resolution forecasting and ensembles.
- **Intelligence-layer leverage:** Fourier neural operators expose regular spectral structure that maps directly to modern accelerators.
- **Software-to-hardware path:** FFT-heavy kernels, tensor operations and ensemble batching are highly hardware-friendly; FPGA FFT pipelines are plausible.
- **P/NP lens:** P approximate simulation surrogate.
- **Maturity:** Established open research code
- **Strategic score:** **4.6/5**

### JAX-MD

- **Repository:** [https://github.com/jax-md/jax-md](https://github.com/jax-md/jax-md)
- **Novelty:** Differentiable molecular-dynamics library built around JAX transformations and accelerator execution.
- **Intelligence-layer leverage:** Makes simulations composable with gradients, optimisation and learned potentials, turning physics engines into trainable modules.
- **Software-to-hardware path:** GPU/TPU execution, neighbour lists, force kernels and differentiable integrators are direct hardware targets.
- **P/NP lens:** P numerical simulation with approximation/error controls.
- **Maturity:** Mature research library and excellent substrate for new discoveries
- **Strategic score:** **4.7/5**

## World models, embodied intelligence and robotics

### V-JEPA 2

- **Repository:** [https://github.com/facebookresearch/vjepa2](https://github.com/facebookresearch/vjepa2)
- **Novelty:** Self-supervised video models intended to support understanding, prediction and planning without reconstructing every pixel.
- **Intelligence-layer leverage:** Predictive latent representations may form a world-model layer that is cheaper and more action-relevant than generative video.
- **Software-to-hardware path:** Video encoders and latent predictors are accelerator-heavy; dense temporal features invite specialised streaming vision hardware.
- **P/NP lens:** P approximate representation learning and planning; action selection can be combinatorial.
- **Maturity:** Official models/code with 2026 extensions; high strategic importance
- **Strategic score:** **4.9/5**

### DreamerV3

- **Repository:** [https://github.com/danijar/dreamerv3](https://github.com/danijar/dreamerv3)
- **Novelty:** Learns a compact world model and trains policies using imagined trajectories across diverse domains.
- **Intelligence-layer leverage:** Imagination converts expensive environment interaction into internal simulation, a central route to more data-efficient agents.
- **Software-to-hardware path:** World-model rollout and actor-critic updates are highly batchable on GPUs/TPUs; simulator and model inference can be co-scheduled.
- **P/NP lens:** Control/planning is heuristic; model learning and rollout are polynomial tensor computation.
- **Maturity:** Strong open reference implementation
- **Strategic score:** **4.8/5**

### TD-MPC2

- **Repository:** [https://github.com/nicklashansen/tdmpc2](https://github.com/nicklashansen/tdmpc2)
- **Novelty:** Scalable model-based RL that plans in learned latent dynamics and supports many continuous-control tasks with shared settings.
- **Intelligence-layer leverage:** Combines planning and value learning in a compact task-oriented latent space, offering a practical path to generalist controllers.
- **Software-to-hardware path:** Short-horizon latent rollouts and trajectory scoring are amenable to batched GPU or FPGA acceleration at low latency.
- **P/NP lens:** Model predictive control search is heuristic and can grow combinatorially with horizon/action branching.
- **Maturity:** Mature research code with models and datasets
- **Strategic score:** **4.7/5**

### OpenVLA

- **Repository:** [https://github.com/openvla/openvla](https://github.com/openvla/openvla)
- **Novelty:** Open vision-language-action model and training stack for generalist robotic manipulation.
- **Intelligence-layer leverage:** Makes robot policy scaling resemble foundation-model scaling while retaining fine-tuning for new embodiments.
- **Software-to-hardware path:** Training uses distributed GPUs; deployment needs quantised low-latency vision-language inference, action decoders and safety monitors on edge accelerators.
- **P/NP lens:** P approximate inference; planning and safe action selection remain difficult.
- **Maturity:** Widely used open research platform
- **Strategic score:** **4.8/5**

### LeRobot

- **Repository:** [https://github.com/huggingface/lerobot](https://github.com/huggingface/lerobot)
- **Novelty:** Open ecosystem of robot interfaces, datasets, pretrained policies and training/deployment tools.
- **Intelligence-layer leverage:** The most important contribution may be standardisation: common data and hardware interfaces allow intelligence to compound across robots.
- **Software-to-hardware path:** Edge GPUs, workstation training, compressed video datasets and hardware plugins make it a full software-to-robotics stack.
- **P/NP lens:** Mostly P systems/inference; policy learning is stochastic and deployment safety is empirical.
- **Maturity:** Rapidly maturing ecosystem with broad community adoption
- **Strategic score:** **4.9/5**

### Octo

- **Repository:** [https://github.com/octo-models/octo](https://github.com/octo-models/octo)
- **Novelty:** Transformer-based generalist robot policy trained on a diverse mixture of robot trajectories.
- **Intelligence-layer leverage:** A reference for cross-embodiment policy transfer and dataset mixture design.
- **Software-to-hardware path:** Large transformer training on GPUs; edge deployment benefits from action token compression, distillation and low-latency kernels.
- **P/NP lens:** Approximate inference and behavioural generalisation; no formal optimality.
- **Maturity:** Open model and code; influential research baseline
- **Strategic score:** **4.6/5**

### Open X-Embodiment

- **Repository:** [https://github.com/google-deepmind/open_x_embodiment](https://github.com/google-deepmind/open_x_embodiment)
- **Novelty:** Unified collection and format for open robotic datasets across many embodiments.
- **Intelligence-layer leverage:** Data interoperability is an intelligence multiplier: it enables larger policies, cross-robot transfer and comparable evaluation.
- **Software-to-hardware path:** Storage, streaming, decoding and distributed sampling are the core systems challenges; computational storage can help at scale.
- **P/NP lens:** P data infrastructure; sampling/mixing policy is heuristic.
- **Maturity:** Large foundational dataset initiative
- **Strategic score:** **4.9/5**

### Diffusion Policy

- **Repository:** [https://github.com/real-stanford/diffusion_policy](https://github.com/real-stanford/diffusion_policy)
- **Novelty:** Models visuomotor control as conditional diffusion over action sequences.
- **Intelligence-layer leverage:** Captures multimodal action distributions and smooth trajectories better than single-step regression in many manipulation settings.
- **Software-to-hardware path:** Repeated denoising creates latency pressure; distilled samplers, FPGA pipelines and edge GPU optimisation are clear opportunities.
- **P/NP lens:** Approximate generative control; action selection remains heuristic.
- **Maturity:** Established open research implementation
- **Strategic score:** **4.6/5**

### ManiSkill

- **Repository:** [https://github.com/haosulab/ManiSkill](https://github.com/haosulab/ManiSkill)
- **Novelty:** GPU-parallel robotics simulation and benchmark suite for manipulation and embodied learning.
- **Intelligence-layer leverage:** Massively parallel simulation supplies the experience needed for RL, imitation and world-model training.
- **Software-to-hardware path:** Direct hardware leverage through GPU physics, rendering and vectorised environments; simulator throughput becomes intelligence throughput.
- **P/NP lens:** Physics stepping is numerical P computation; policy search is heuristic.
- **Maturity:** Active benchmark/simulation ecosystem
- **Strategic score:** **4.8/5**

### Genesis

- **Repository:** [https://github.com/Genesis-Embodied-AI/genesis-world](https://github.com/Genesis-Embodied-AI/genesis-world)
- **Novelty:** High-performance simulation platform for general-purpose robotics and embodied-AI learning.
- **Intelligence-layer leverage:** A fast, programmable world generator and simulator can become the substrate for synthetic experience and automated curriculum generation.
- **Software-to-hardware path:** Strong GPU kernel and compiler opportunity across rigid/soft-body physics, rendering and parallel environment execution.
- **P/NP lens:** Simulation is numerical; scenario generation and control search are heuristic.
- **Maturity:** Fast-moving open-source platform under active development
- **Strategic score:** **4.7/5**

### Isaac Lab

- **Repository:** [https://github.com/isaac-sim/IsaacLab](https://github.com/isaac-sim/IsaacLab)
- **Novelty:** Open robot-learning framework built on accelerated simulation, supporting RL, imitation and large-scale training.
- **Intelligence-layer leverage:** Integrates realistic simulation, sensors, robots and learning workflows in a reproducible stack.
- **Software-to-hardware path:** Tightly coupled to GPU simulation and rendering; strong datacenter-to-edge deployment path.
- **P/NP lens:** Numerical simulation plus heuristic policy optimisation.
- **Maturity:** Mature industrial research framework
- **Strategic score:** **4.7/5**

### Habitat-Lab

- **Repository:** [https://github.com/facebookresearch/habitat-lab](https://github.com/facebookresearch/habitat-lab)
- **Novelty:** Simulation and embodied-AI platform for navigation, rearrangement and interactive agents.
- **Intelligence-layer leverage:** Provides rich environments and benchmarks for long-horizon spatial intelligence, memory and planning.
- **Software-to-hardware path:** GPU rendering, CPU simulation, vectorised environments and distributed evaluation are key; world-model rollouts can reduce simulator cost.
- **P/NP lens:** Long-horizon planning is combinatorial; learned policies and planners are heuristic.
- **Maturity:** Established open research platform
- **Strategic score:** **4.6/5**

## Cross-project technical opportunities

### 1. The adaptive inference runtime
A serving layer that can apply ephemeral or persistent parameter deltas, evaluate whether an update helped, isolate tenant state, roll back regressions and move memory between HBM, DRAM, CXL and SSD. TTT-LM, In-Place TTT, Doc-to-LoRA, MemoryLLM and KV-compression projects are upstream research components of this product category.

### 2. The verifier fabric
A common service for tests, proof assistants, SQL/database constraints, simulators, symbolic equivalence, numerical tolerances and policy checks. Agentic RL projects currently rebuild these reward channels independently. A verifier fabric could make experience portable across trainers and agents.

### 3. The autonomous experiment operating system
An experiment graph, immutable provenance log, result memory, budget controller, sandbox manager and evaluator API that can serve OpenEvolve, DGM, AI Scientist, autoresearch and scientific-model pipelines. The defensible asset would be accumulated evaluator traces and hardware-aware cost models.

### 4. Proof-carrying agent actions
Combine neural proposal systems with formal or executable certificates: Lean proofs for mathematics, compiler translation validation for code changes, tests for software repair, conservation laws for simulation, and constraint checkers for schedules. This is the strongest route from impressive demos to high-stakes deployment.

### 5. Scientific foundation-model compilation
Equivariant graph networks, diffusion samplers, Fourier operators and differentiable simulators currently rely on general GPU stacks. A compiler that recognises geometric tensor products, neighbour lists, mesh transforms, batched relaxations and ensemble structure could create a reusable AI-for-science accelerator layer.

### 6. Experience-generation infrastructure
OpenEnv, Agent World Model, ManiSkill, Genesis, Habitat and scientific simulators all point to the same bottleneck: useful verified experience. The platform opportunity is to generate, version, distribute and replay environments at scale while keeping expensive model workers saturated.

## Research cautions

- **Benchmark recursion:** a self-improving system can overfit its evaluator while appearing to improve. Hold-out environments and external replication are mandatory.
- **Runtime learning safety:** online updates can introduce poisoning, user leakage or irreversible behaviour drift. Parameter state must be versioned and auditable.
- **Scientific validity:** a generated equation, molecule or paper is a hypothesis until independently checked experimentally or formally.
- **Open-source depth:** “open code” may omit training data, weights, preprocessing, exact internal configurations or commercially permissive licences.
- **Complexity honesty:** more compute and better heuristics expand the tractable instance envelope but do not make general NP-hard search polynomial.
