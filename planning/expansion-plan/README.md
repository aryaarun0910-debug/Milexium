# Milexium expansion blueprint

This folder is an executable product and company blueprint. The original
`highLevel.md` brainstorm has been removed; the numbered documents are now the
maintained source of truth for strategy, contracts, implementation, evidence,
commercialization, and long-term research.

Claude Code and other implementation swarms should begin with
[`CLAUDE.md`](CLAUDE.md) and [`SWARM_MANIFEST.yaml`](SWARM_MANIFEST.yaml).

The existing Milexium product is the first executable vertical of the complete
system:

- Paratransit is the beachhead.
- Real aggregate demand forecasts and their stated limitations remain the current
  evidence.
- Trip-level scheduling remains a fictional-reference-agency proof until a
  consented operator dataset exists.
- Connect, MilexiumDB, Core, Forecast, Decide, Verify, Replay, Explain, Forge,
  Fabric, Runtime, Edge, and software-to-silicon backends are all part of the
  specified expansion.
- Parallel agent execution is assumed. Dependencies are controlled through
  contracts, conformance fixtures, independent verifiers, and integration
  trains rather than calendar sequencing.

## The blueprint

| Document | Decision it owns |
|---|---|
| [01 — North star and boundaries](blueprint/01-north-star-and-boundaries.md) | What Milexium is becoming, what "unavoidable" means, and the truth/safety boundaries |
| [02 — Platform architecture](blueprint/02-platform-architecture.md) | Layering, component contracts, deployment shape, and build-versus-buy rules |
| [03 — Connect and standards](blueprint/03-connect-and-standards.md) | Vendor-neutral ingestion, transport standards, validation, and adapter strategy |
| [04 — MilexiumDB](blueprint/04-milexiumdb-canonical-state.md) | Canonical transport state, temporal records, tenancy, lineage, and outcomes |
| [05 — Core and Forecast](blueprint/05-core-model-runtime-and-forecast.md) | Model-agnostic task runtime, uncertainty, registry, routing, and monitoring |
| [06 — Decide](blueprint/06-decide-policy-and-optimisation.md) | Constraints, policies, solver abstraction, alternatives, and safe degradation |
| [07 — Explain and Replay](blueprint/07-explain-replay-and-evidence.md) | Decision evidence, temporal replay, simulation, exports, and claim boundaries |
| [08 — SDK and APIs](blueprint/08-sdk-api-and-developer-experience.md) | Public interfaces, compatibility, plugin system, errors, and ten-minute adoption |
| [09 — Benchmark and research](blueprint/09-benchmark-data-and-research.md) | Evaluation suite, data ladder, leaderboards, model registry, and paper agenda |
| [10 — Security and governance](blueprint/10-security-privacy-and-ai-governance.md) | Threats, PHI posture, tenant controls, human oversight, and procurement evidence |
| [11 — Competition and positioning](blueprint/11-competition-and-positioning.md) | Market map, wedge, claims discipline, and differentiation tests |
| [12 — Open core and defensibility](blueprint/12-open-core-business-and-defensibility.md) | What to open, what to sell, licensing, packaging, and the compounding moat |
| [13 — Go to market and ecosystem](blueprint/13-go-to-market-and-ecosystem.md) | Beachhead, adoption loops, pilot design, channels, and adapter expansion |
| [14 — Parallel execution roadmap](blueprint/14-execution-roadmap.md) | Full dependency-based program graph and integration evidence for every platform layer |
| [15 — Risks and falsification](blueprint/15-risks-and-falsification.md) | Assumption register, experiments, adaptation triggers, and strategic failure modes |
| [16 — Semantic state and TurboVec](blueprint/16-semantic-state-and-turbovec.md) | MilexiumDB state-machine design, semantic retrieval, TurboVec evaluation, vendoring, and scientific R&D |
| [17 — 250 GB data estate](blueprint/17-data-and-storage-readiness.md) | Exact data portfolio, acquisition, storage layout, semantic/experience capacity, and lifecycle |
| [18 — Software-to-silicon intelligence architecture](blueprint/18-software-to-silicon-intelligence-architecture.md) | Complete mapping of all 80 technologies and 72 projects into Milexium products, IRs, and compounding loops |
| [19 — Agent-swarm execution system](blueprint/19-agent-swarm-execution-system.md) | Work packets, swarm topology, contract hierarchy, merge trains, evaluators, and autonomous improvement |
| [20 — Dossier coverage ledger](blueprint/20-dossier-coverage-ledger.md) | Traceability for all 80 software-to-silicon technologies and all 72 intelligence-layer projects |
| [Sources](blueprint/SOURCES.md) | Authoritative sources used across the blueprint |

## Status language

Every future implementation document and public claim should use these labels:

- **Exists:** working code or evidence in the current Milexium repository.
- **Specified:** interface or design is documented but not implemented.
- **Demonstrated:** works on the fictional reference agency or public proxy data.
- **Validated:** tested on consented operator data against a pre-agreed baseline.
- **Production:** operated with security controls, monitoring, recovery, support,
  and a named accountable owner.

Never let "specified" or "demonstrated" silently become "validated."

## Recommended reading paths

- YC or investor: 01 → 11 → 18 → 14 → 15.
- Engineer: 02 → 18 → 14 → 19 → relevant product contract.
- Operator or design partner: 01 → 07 → 10 → 13.
- Research collaborator: 09 → 16 → 18 → 14.
- Data and infrastructure owner: 03 → 04 → 16 → 17 → 18.
- Agent-swarm orchestrator: 18 → 20 → 14 → 19 → 15.
