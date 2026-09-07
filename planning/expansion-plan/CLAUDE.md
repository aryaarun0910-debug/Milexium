# Milexium expansion implementation instructions

## Mission

Implement the complete Milexium expansion described in this folder through
parallel, contract-driven agent work.

The implementation repository is:

```text
C:\Users\aryaa\Documents\Milexium
```

This expansion-plan folder is the product and architecture specification. Do not
mistake it for the implementation repository.

## Mandatory reading order

Before dispatching implementation agents, read:

1. `README.md`
2. `blueprint/01-north-star-and-boundaries.md`
3. `blueprint/18-software-to-silicon-intelligence-architecture.md`
4. `blueprint/20-dossier-coverage-ledger.md`
5. `blueprint/14-execution-roadmap.md`
6. `blueprint/19-agent-swarm-execution-system.md`
7. `blueprint/10-security-privacy-and-ai-governance.md`
8. `blueprint/15-risks-and-falsification.md`

Then read the product-specific blueprint documents owned by the workstream.
`blueprint/SOURCES.md` and
`software_to_silicon_markdown_dossier/software_to_silicon_markdown/` provide
research provenance.

## Authority order

When documents or implementations disagree, use:

1. safety, privacy, legal, and tenant-isolation invariants;
2. canonical domain semantics and state transitions;
3. published schema and API contracts;
4. evidence, verifier, and replay contracts;
5. benchmark definitions;
6. implementation design;
7. optimization preferences.

Never alter upstream meaning merely to make a local implementation pass.

## Truth rules

Use these labels exactly:

- **Exists:** working in the current repository.
- **Specified:** documented but not implemented.
- **Demonstrated:** works on public proxy or fictional reference data.
- **Validated:** tested on consented operator data against a declared baseline.
- **Production:** operated with security, monitoring, recovery, support, and an
  accountable owner.

Do not promote specified or demonstrated claims into validated claims.

## Parallel execution

Use `SWARM_MANIFEST.yaml` for the workstream graph. Convert each capability into
the work-packet format in
`blueprint/19-agent-swarm-execution-system.md`.

Every dispatched packet must declare:

- objective;
- owned implementation paths;
- read-only dependencies;
- normative contracts;
- fixtures;
- required outputs;
- acceptance commands;
- performance budget;
- security/privacy invariants;
- failure injections;
- downstream consumers.

Agents must own disjoint paths wherever possible. Contract changes require an
architecture decision record and compatibility update.

## Implementation invariants

- PostgreSQL/PostGIS is authoritative operational state.
- Object storage holds immutable source and artifact objects.
- Vector, graph, feature, and analytical stores are derived projections.
- State-machine transitions, authorization, policy, and hard constraints never
  depend solely on model or vector similarity.
- Candidate generators and independent verifiers remain separate.
- Every result pins data, schema, policy, model, solver, index, runtime, and
  randomness versions as applicable.
- Every derived artifact is reproducible or explicitly classified as
  irreplaceable.
- Every optimization retains an exact or bounded-quality reference and fallback.
- Tenant isolation is tested adversarially at storage, index, cache, artifact,
  event, model-memory, and execution layers.
- The website/domain are owned separately by Chris; this repository contains no
  top-level `web` package and implementation agents must not recreate one unless
  given a separate explicit instruction.

## Integration requirements

Before merging any workstream:

1. run unit, type, lint, and format checks;
2. run schema/API compatibility and conformance fixtures;
3. run property, metamorphic, fuzz, and adversarial tests where applicable;
4. run tenant/privacy/security tests;
5. run replay and deterministic artifact checks;
6. run failure injection and recovery tests;
7. run quality, latency, memory, storage, and cost regressions;
8. generate SBOM, license, source-provenance, and evidence manifests;
9. execute documentation and examples;
10. write the packet handoff described in blueprint 19.

## Git and workspace discipline

- Inspect the implementation repository and its instructions before editing.
- Preserve unrelated user changes.
- Use a dedicated branch/worktree per independent packet.
- Do not allow multiple agents to edit the same contract concurrently.
- Do not merge generated output that cannot be regenerated.
- Pin external dependencies by version and commit.
- Preserve upstream licenses and maintain `THIRD_PARTY_NOTICES` and patch
  manifests.
- Integration agents adjudicate merges; implementation agents do not approve
  their own contract exceptions.

## Completion

A capability is covered only when it has:

- a versioned normative contract;
- implementation plus independent verifier;
- conformance, adversarial, and recovery evidence;
- measured quality and systems performance;
- replay/evidence support;
- security, privacy, licensing, and provenance records;
- rollback and compatibility paths;
- executable documentation;
- an accountable owner.

Agent count, token spend, branches, and code volume are not completion evidence.
