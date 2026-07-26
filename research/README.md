# research/

Milexium Forge and Experience Fabric research: experiment protocols, results,
and negative results, per `blueprint/18-software-to-silicon-intelligence-architecture.md`
and `blueprint/19-agent-swarm-execution-system.md` in the expansion plan.

- **`protocols/`** — experiment DAG definitions and evaluation protocols, written
  before an experiment runs.
- **`experiments/`** — dated experiment records: hypothesis, method, result.
- **`negative-results/`** — experiments that failed or found no effect, kept
  deliberately (this repository already does this in `realdata/` — e.g. the
  weather-ablation negative result — and the expansion continues that practice
  at platform scale rather than discarding it).

**Owner:** Forge/Fabric workstream (Program J). Mutation agents cannot edit their
own promotion policy or hidden evaluators — those live in `knowledge/architecture/contracts/`
and `evidence/conformance/adversarial/`, not here.

**Version policy:** append-only. An experiment record is never deleted, only
superseded by a dated follow-up that references it.

**Test command:** none — this directory holds records, not executable code.
