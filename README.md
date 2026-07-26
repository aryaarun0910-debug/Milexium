# Milexium

Explainable demand forecasting and scheduling evidence for US paratransit and
NEMT operators.

Milexium is built around one operational promise: **every forecast, scheduling
recommendation, denial and human override should be reviewable after the fact.**
When a board, an auditor, a disability advocate or the FTA asks *why*, the answer
should already exist rather than be reconstructed.

## The architecture, in one sentence

> **Themis** governs what is true and permissible.
> **Metis** proposes what should happen next.
> **Aletheia** proves why the decision was made.
> **Argus** lets the operator see, question and control it.
> **Talos** keeps it running.

Each layer is an **authority boundary**, not a folder of convenience. The names
exist so the boundaries can be pointed at — and so they can be tested.

| Layer | Must never |
|---|---|
| **Themis** | infer uncertain facts and silently store them as reality |
| **Metis** | alter canonical state, or authorise an operation |
| **Aletheia** | depend on hidden Milexium runtime to verify a claim |
| **Argus** | invent a fact, constraint, reason or recommendation |
| **Talos** | ship an incompatible change without preserving reproducibility |

Metis holds today by construction — it imports types and vocabularies from
Themis, never a store or a writer. Aletheia's is enforced against the verifier's
own syntax tree. The rest are being made enforceable rather than documented.

## Status — read this before quoting anything

**Every capability in this repository is at most *Demonstrated*.**

Under [ADR-0001](forge/knowledge/architecture/decisions/0001-adopt-expansion-blueprint-and-control-plane.md)
the status **Validated** requires consented operator data against a declared
baseline, and Milexium has none: **no customers, no pilots, no operator data.**
Public aggregate data can *demonstrate* a forecasting task. It cannot *validate*
operator capacity planning, scheduling, denial explanation, or economic impact.

The binding rule for anything outward-facing is in
[COMPETITIVE_POSITIONING.md](forge/knowledge/docs/COMPETITIVE_POSITIONING.md):
never write *validated*, *proven* or *guaranteed*; never publish a savings, ROI
or opportunity figure; every number names its artifact or is deleted.

The model recommendation is deliberately conventional — XGBoost beat the
experimental transformer on the same real Access-A-Ride holdout, so the tree
model is the **local reference implementation**. Nothing here is deployed to or
running for an operator.

## Repository map

| Directory | What lives there |
|---|---|
| `themis/` | Governed reality — `canonical`, `ontology`, `connect`, `estate`, `core`. Schema, identity, legal state transitions, provenance, custody |
| `metis/` | Bounded intelligence — `forecast`, `decide`. Demand models, the CP-SAT solver portfolio, pooling and capacity value |
| `aletheia/` | Reproducible evidence — `evidence`, `verify`, `replay`, plus `conformance` (the tests), `benchmarks`, `artifacts` |
| `argus/` | The operational surface — `api`, `sdk`, `sdk-typescript`, `demo`. The command centre lands here |
| `talos/` | Dependable delivery — `infra`, `ops`, `contracts`, `tools` |
| `forge/` | Where we build it — `knowledge` (ADRs, docs, packets), `research`, `business`, `legacy` |
| `data/` | The governed corpus — `acquired/` and `curated/` |

`forge/` may import anything; **nothing may import `forge/`.** Research, business
material and architectural records reference the product freely; the product
never references them.

`forge/legacy/` means **relocated, not removed** — `forge/legacy/kaggle/` holds
the transformer experiment whose *negative* result is cited evidence in
[MODEL_CARDS.md](forge/knowledge/docs/MODEL_CARDS.md).

### The two data trees, and why they are named that way

`data/acquired/` came through `themis/estate` — checksum-verified, free-space
guarded, quarantined before promotion. `data/curated/` was hand-acquired before
that pipeline existed. Both declare rights in committed manifests (ADR-0053); the
only real distinction is **how the bytes got here**, so that is what they are
named for.

Large raw zones, checkpoints, trained models, predictions, outreach drafts and
credentials are local-only and gitignored — see
[DATA_STORAGE.md](forge/knowledge/docs/DATA_STORAGE.md).

## Running it

```bash
py -3 -m pytest                        # the full suite
py -3 -m argus.demo                    # end-to-end walkthrough, ~2.5s
py -3 talos/tools/audit_repository.py  # structure, data boundaries, integrity
```

The demo's best moments are its **refusals**: PII quarantined ahead of all other
validation, an ambiguous date declined while its unambiguous twin is repaired, a
denial left without a reason rather than back-filled, no savings figure without
the operator's own cost split, and a conformal interval withdrawing its own
coverage guarantee under measured drift. It ends by verifying itself.

## Start here

- [Implementation status](IMPLEMENTATION_STATUS.md) — Exists / Specified /
  Demonstrated across programs A–M
- [Documentation index](forge/knowledge/docs/README.md)
- [Architecture decisions](forge/knowledge/architecture/decisions/) — each
  recording what was decided *and what it costs*
- [Journal](forge/knowledge/docs/JOURNAL.md) — append-only session record
- [Competitive positioning](forge/knowledge/docs/COMPETITIVE_POSITIONING.md)

The public website and `milexium.com` infrastructure are owned by Chris and live
outside this repository. This repository is the product, data, modelling and
technical-evidence workspace.
