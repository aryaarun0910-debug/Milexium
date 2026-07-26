# ADR-0077: Enforcing the layer prohibitions — and the three claims that were false

- **Status:** Accepted
- **Date:** 2026-07-26
- **Packet:** MX-ARCH-PROHIBITIONS-016
- **Corrects:** ADR-0076 and the README's first dependency table

## Context

ADR-0076 named five authority layers and gave each a prohibition. **They were
prose.** In this repository a rule in prose is a rule that decays — proven most
recently when "append-only" turned out to be a coding convention that a direct
SQL `UPDATE` walked straight through (ADR-0063 → ADR-0074).

## Decision

**141 tests across four files**, asserted against the **AST** rather than by
grepping strings.

| Prohibition | Now | Violating case constructed |
|---|---|---|
| Dependency direction | **Enforced** across all five layers | metis→argus, themis→aletheia, themis→forge, import nested in `def/if/try` — all RED, naming file, line, statement and rule |
| `forge` isolation | **Enforced on both channels** | a direct import **and** `spec_from_file_location` on a forge path — both RED. Reading a forge file with `.read_text()` stays GREEN: *a citation is not a dependency* |
| Metis | **Enforced**, 8 checks | store import, `sqlite3`, `PersistentModelRegistry`, duck-typed `store.append_event()`, `registry.promote()`, `open(p,"w")` — all RED; `list.append` stays GREEN |
| Themis | **Partial**, uncovered half named in the docstring | provenance defaulted, `probability` defaulted to 1.0, unfrozen record — all RED |
| Argus | **Partial**, written *before* the layer arrived | invented `reason=`/`confidence=`, `import anthropic`, `import xgboost`, `random.shuffle`, composed SDK returns — all RED; honest pass-through GREEN |

34 violating cases against the real tree, 9 fed directly to the walkers, and 6
honest-code controls that must stay GREEN. Probes were throwaway modules or
in-memory mutations — never edits to another agent's files.

## The three claims this proved false

ADR-0076 and the README asserted a dependency table. **Writing the test showed it
did not describe the code.**

1. **"Metis imports types and vocabularies, never a store or a writer" — false.**
   Metis imports `themis.core.model_registry`, which carries `CoreDatabase`,
   `register()`, `promote()` and `PersistentModelRegistry`. Metis *calls* only
   `champion(task)`, so the prohibition **rests on discipline, not structure**, in
   that one place. Pinned with the mutator names derived from the live class.
2. **"`talos → nothing`" and "`aletheia → themis`" — both inaccurate.**
   `talos/contracts/generate.py` imports `argus.api.app`; `aletheia/benchmarks/`
   imports `metis` in 78 places. The load-bearing halves are clean with zero
   exemptions; the tooling edges are not.
3. **`aletheia/verify/formal.py` executes Python out of `forge/`.** A *shipping*
   module loads and runs `forge/knowledge/architecture/formal/*.py` by file path
   at import time — confirmed by `sys.modules` entries whose `__file__` is under
   `forge/`. **An AST import walk is structurally blind to this**, which is the
   same shape as ADR-0074's defect: a rule enforced on one channel while a second
   goes around it. Pinned, and the pin **fails in both directions** so the
   exemption cannot outlive its cause.

## Two design changes forced mid-flight, both improvements

Concurrent packets landed underneath this one:

- `argus/command_centre/` appeared and the first classification rule went red on
  it for a reason unrelated to direction. The default flipped to **fail-safe:
  exemption is opt-in, everything else is policed.** It is bound by the direction
  from its first commit.
- `themis/ontology/episode.py` appeared, and a **fixed module list would have
  skipped it silently** — the exact failure this packet exists to prevent. The
  Themis survey is now **discovered from the tree**, not enumerated.

## What could not be mechanised, stated rather than implied

- **Themis: an inference that lies.** Nothing stops
  `SnapshotFact(fact_class=OBSERVATION, quality=TRUSTED, value=<a guess>)` —
  Python cannot distinguish a measured 12.0 from an imputed one. The honest claim,
  in the docstring: *Themis makes an honest ingest impossible to get wrong, and
  does not make a dishonest one impossible.*
- **Argus:** the demo's narrative prose, the generated TS SDK, and the command
  centre's internals.

## A fourth finding, from a mutation that came back GREEN

`DEFAULT_MATCH_THRESHOLD` **is not enforced at construction** — a 0.61-vs-0.39
identity merge is recordable, requiring only unique-argmax plus a named rule,
while the class docstring reads as though it is impossible. Found because a
mutation returned GREEN; per standing rule the *mutation* was checked first, and
the mutation was wrong. Now asserted in both directions.
