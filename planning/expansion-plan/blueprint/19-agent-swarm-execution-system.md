# Agent-swarm execution system

## Objective

This is the operating specification for turning the blueprint into parallel
engineering work. It assumes abundant agent, token, model, and compute capacity.
The scarce resources are coherent interfaces, trustworthy evaluation, merge
bandwidth, and architectural consistency.

Agents work concurrently against immutable contracts. They do not coordinate by
sharing an informal understanding of the product.

## Repository control plane

Create these root artifacts before launching implementation swarms:

```text
/architecture
  /decisions                 Architecture decision records
  /contracts                 Normative schemas and interface definitions
  /threat-models
  /formal                    TLA+, Lean, SMT and invariant specifications
/packages
  /connect
  /canonical
  /core
  /forecast
  /decide
  /verify
  /replay
  /explain
  /forge
  /fabric
  /runtime
  /edge
/conformance
  /fixtures
  /goldens
  /property-tests
  /adversarial
/benchmarks
  /quality
  /systems
  /cost
/research
  /protocols
  /experiments
  /negative-results
/third_party
/ops
  /observability
  /recovery
  /security
```

Each directory has an owner file, normative README, version policy, and test
command. Generated code and schemas identify their source.

## Contract hierarchy

When artifacts disagree, authority follows this order:

1. safety, privacy, legal, and tenant-isolation invariants;
2. canonical domain semantics and state-transition specifications;
3. published API/schema contracts and compatibility tests;
4. evidence, verifier, and replay contracts;
5. benchmark definitions and acceptance thresholds;
6. implementation design;
7. optimization and agent preferences.

An agent cannot redefine an upstream meaning to make its local tests pass.

## Work packet format

Every agent receives a bounded, independently verifiable packet:

```yaml
id: MX-WORKSTREAM-CAPABILITY-###
objective: One observable outcome
owned_paths: []
read_only_dependencies: []
normative_contracts: []
inputs_and_fixtures: []
required_outputs: []
acceptance_commands: []
performance_budget: {}
security_and_privacy_invariants: []
failure_injections: []
compatibility_matrix: []
evidence_to_emit: []
forbidden_interface_changes: []
upstream_blockers: []
downstream_consumers: []
```

“Build MilexiumDB” is not a work packet. “Implement bitemporal
`ServiceRequest` transitions against schema v0.3, including idempotency,
correction, concurrent-version, and replay fixtures” is.

## Parallel workstream graph

### Contract and ontology swarm

Owns canonical entity definitions, state machines, identifiers, time semantics,
policy vocabulary, metric definitions, and sensitivity classifications.

Outputs:

- JSON Schema/OpenAPI/Protobuf or equivalent;
- relational DDL and constraints;
- event schemas;
- examples, counterexamples, and migration fixtures;
- semantic-loss rules;
- formal invariants.

### Connect swarm

Builds generic and vendor/standards adapters, schema inference, reconciliation,
data-quality reports, lineage, incremental imports, and streaming ingestion.
Each adapter targets the canonical conformance suite rather than another
adapter's implementation.

### State and storage swarm

Builds bitemporal state, event log, transactional outbox, object manifests,
feature snapshots, semantic case projection, retention, deletion, backup, and
recovery.

### Forecast and science swarm

Builds baselines, hierarchical models, state-space/graph/spectral models,
survival models, conformal calibration, drift/change detection, model registry,
and champion/challenger evaluation.

### Optimization swarm

Builds Decision IR, CP-SAT/MILP/SMT/MaxSAT/heuristic backends, decomposition,
kernelization, approximation contracts, learning-guided search, GPU-batched
bounds, rolling recovery, and independent solution validation.

### Verifier and formal swarm

Builds schema, state, policy, feasibility, numerical, statistical, security,
replay, compiler, and proof verifiers. It owns the small trusted kernels and
must be organizationally separate from candidate generators.

### Simulation and world-model swarm

Builds discrete-event models, synthetic agencies, disruption generators,
facility/queue/fleet dynamics, learned residuals, latent world models, scenario
ensembles, calibration, and sim-to-real checks.

### Memory and retrieval swarm

Builds semantic cases, metadata/bitmap filters, TurboVec/pgvector/DiskANN/exact
adapters, learned memory policies, adapter/delta registry, memory compaction,
reconciliation, and retrieval evaluation.

### Evidence and experience swarm

Builds Evidence IR, Experience IR, provenance graphs, minimal causal slices,
decision packets, replay manifests, operator precedents, trace capture, and
machine-readable exports.

### Forge and agent-learning swarm

Builds experiment DAGs, OpenEnv-compatible environments, sandboxes, curriculum
generation, evolutionary archives, RL adapters, evaluator routing, budget/cost
controls, and artifact promotion.

### Runtime and compiler swarm

Builds Execution IR, profilers, cost models, kernel library, equality-saturation
rewrites, MLIR/Triton lowering, quantization, sparse layouts, streaming sketches,
zero-copy I/O, and CPU/GPU backend dispatch.

### Confidential and edge swarm

Builds tenant-scoped execution, key management, attestation, secure plugins,
offline state, signed bundles, memory-safe agents, confidential analytics, and
privacy-preserving computation adapters.

### Product/API swarm

Builds CLI, SDKs, HTTP/event APIs, workflows, administration, developer portal,
operator review surfaces, and integration examples entirely against normative
contracts.

### Reliability and adversarial swarm

Attacks every layer using corruption, races, partial failure, future leakage,
tenant crossing, malicious inputs, evaluator gaming, drift, numerical edge
cases, and recovery drills. It owns no production implementation.

## Dependency rules

Parallelism is maximized through four kinds of dependency:

- **schema dependency:** generated types from a pinned contract version;
- **behavior dependency:** executable conformance fixtures and golden traces;
- **service dependency:** mock server or test container with a versioned API;
- **artifact dependency:** immutable model/index/policy/proof manifest.

Agents can begin when a dependency has a versioned stub plus conformance tests.
They do not wait for the final downstream implementation.

## Integration trains

Every merge train runs:

1. format, type, lint, and unit tests;
2. schema/API compatibility checks;
3. contract and golden-fixture tests;
4. property, metamorphic, and fuzz tests;
5. tenant/privacy/security adversarial tests;
6. exact replay and deterministic artifact checks;
7. failure injection and recovery tests;
8. model/solver quality regression tests;
9. p50/p95/p99, memory, storage, and cost regression tests;
10. SBOM, license, provenance, and secret scans;
11. documentation/example execution;
12. evidence-manifest generation.

Performance improvements cannot merge when they weaken verifier independence,
tenant isolation, replay, or stated quality bounds.

## Branch and ownership discipline

- One work packet owns a disjoint path set.
- Cross-contract changes require an ADR and contract-version update.
- Agents never rewrite unrelated files to reduce conflicts.
- Generated code is regenerated, not hand-edited.
- External projects are pinned by version and commit with license and patch
  manifests.
- Large refactors provide compatibility shims and migration fixtures.
- Integration agents merge completed packets; implementation agents do not
  adjudicate their own contract disputes.

## Evaluation architecture

Maintain four evaluator partitions:

| Partition | Visibility | Purpose |
|---|---|---|
| Development | Full | Rapid agent feedback |
| Regression | Full after completion | Prevent known failures |
| Holdout | Hidden from candidate agents | Measure generalization |
| Adversarial | Controlled by independent swarm | Detect gaming and unsafe behavior |

Rotate holdouts and generate metamorphic variants. Promotion requires improvement
across the relevant vector of correctness, quality, robustness, cost, and
operational burden. A single benchmark score never controls promotion.

## Agent memory

Agents receive:

- the relevant contracts and ADRs;
- package-local documentation;
- known failure corpus;
- previous experiment summaries;
- exact acceptance commands;
- explicit non-owned paths.

They do not receive the entire unfiltered repository context by default.
Provenance slicing and semantic retrieval construct the smallest sufficient
context, reducing contradictions and token waste.

Every concluded packet writes a compact handoff:

```text
Implemented
Contract versions
Files owned/changed
Commands and results
Known limitations
New risks
Generated artifacts and hashes
Downstream integration notes
```

## Autonomous research loop

Forge may continuously generate candidate improvements:

```text
hypothesis
  -> isolated branch/environment
  -> code/model/policy/kernel mutation
  -> compile and verify
  -> benchmark and failure injection
  -> hidden evaluation
  -> archive result
  -> challenger or rejection
```

Population-based archives retain diverse candidates and negative results.
Evaluation policies, holdouts, and trusted verifiers are read-only to mutation
agents. This permits aggressive autonomous improvement without allowing an agent
to mark its own output correct.

## Completion definition

The swarm has “covered” a blueprint capability only when it produces:

- an implemented and versioned contract;
- passing conformance and adversarial tests;
- reproducible build and deployment artifacts;
- measured quality and systems benchmarks;
- telemetry and failure handling;
- security and privacy evidence;
- operator/developer documentation;
- an owner and upgrade path;
- a machine-readable evidence manifest.

Lines of code, agent count, token spend, and number of parallel branches are
inputs—not completion evidence.
