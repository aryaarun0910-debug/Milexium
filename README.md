# Milexium

Explainable demand forecasting and scheduling support for US paratransit and
NEMT operators. Every mile, justified (tagline, tentative). Milexium is being
built around a simple operational promise: every forecast, scheduling
recommendation, rejection, and human override should be reviewable after the
fact.

The model recommendation is deliberately conventional: XGBoost beat the
experimental transformer on the same real Access-A-Ride holdout, so the tree
model remains the **local reference implementation** — nothing here is deployed
to or running for an operator. See [realdata/README.md](realdata/README.md) for
the full comparison and limitations.

**Status:** every capability in this repository is at most **Demonstrated**.
Under [ADR-0001](knowledge/architecture/decisions/0001-adopt-expansion-blueprint-and-control-plane.md)
the status **Validated** requires consented operator data against a declared
baseline, and Milexium has none — no customers, no pilots, no operator data.
Public aggregate data can demonstrate a forecasting task; it cannot validate
operator capacity planning, scheduling, denial explanation, or economic impact.
The binding rule for anything outward-facing is in
[knowledge/docs/COMPETITIVE_POSITIONING.md](knowledge/docs/COMPETITIVE_POSITIONING.md).

## Repository map

The repository has two layers. The **product & evidence workspace** is the
original real-data forecasting, market-sizing, and demonstration work. The
**expansion platform** is the contract-driven runtime being built per the
`Milexium Expansion plan` blueprint — see
[`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md) for what is actually
Exists vs. Specified in each program.

Top level, grouped by concern:

| Directory | What lives there |
|---|---|
| `app/` | The product — one Python package per program, plus the TypeScript SDK |
| `platform/` | How it is built and run — `platform/infra`, `platform/ops`, `platform/contracts`, `platform/tools` |
| `evidence/` | The proof it works — `evidence/conformance`, `evidence/benchmarks`, `evidence/artifacts` |
| `knowledge/` | Why it is the way it is — `knowledge/architecture` (ADRs), `knowledge/docs`, `knowledge/workstreams` |
| `data/` | The governed data estate — committed manifests, gitignored zones |
| `realdata/` | Public-data panels, model training, and the committed evidence outputs |
| `research/` | R&D hypotheses and their recorded results, including the killed ones |
| `demo/` | The end-to-end walkthrough (`py -3 -m demo`) |
| `business/` | `business/outreach`, `business/ntd`, `business/reference_agency` |
| `_legacy/` | Relocated, not removed — `_legacy/kaggle`, `_legacy/third_party`, `_legacy/crates` |

`realdata/` deliberately stays at the top level: its paths are pinned by sha256
in the evidence registry and read directly by the forecast, leakage and teardown
suites, so moving it would break recorded provenance to buy tidiness.

### Product & evidence workspace

| Path | Purpose |
|---|---|
| `realdata/` | Public-data ingestion, derived demand panels, model training, evaluation, and compact evidence outputs |
| `business/ntd/` | FTA National Transit Database economics, market sizing, and outreach inputs |
| `business/reference_agency/` | Fictional, synthetic trip-level agency used only for scheduler and audit-trail demonstrations |
| `_legacy/kaggle/` | GPU notebook + recorded transformer experiment — kept **negative-result evidence** (XGBoost beat it; cited in `knowledge/docs/MODEL_CARDS.md`), not dead code |
| `business/outreach/` | Design-partner pitch, cold-email templates, target tables (drafts locally gitignored) — the shadow-mode-pilot toolkit |
| `knowledge/docs/` | Roadmap, source catalog, model cards, research questions, journal, YC draft |
| `evidence/artifacts/` | Curated generated screenshots and dated knowledge-graph snapshots |
| `platform/tools/` | Repository and data integrity checks |

### Expansion platform (the transport decision runtime)

| Path | Purpose |
|---|---|
| `app/` | One package per program: `canonical` (A), `connect` (B), `estate` (C data layer), `core` (D), `forecast` (E), `verify` (G), `evidence` (I), `sdk` (M) |
| `knowledge/architecture/` | ADRs (`decisions/`), normative contracts, threat models, formal specs |
| `evidence/conformance/` | Executable proof: fixtures, property tests, adversarial tests (the evidence behind every "Exists"/"Demonstrated" claim) |
| `data/` | Governed data estate — `catalog/` (committed manifests + rights) with gitignored raw/derived zones; acquire via `app/estate`. 250 GB is the *design target* for this estate, not its current governed volume |
| `knowledge/workstreams/` | Work packets + the `DOSSIER_COVERAGE.md` 80-tech/72-project ledger |
| `evidence/benchmarks/`, `research/`, `_legacy/third_party/`, `platform/ops/` | Perf/quality benchmarks, experiment records, the vendoring gate, and ops readiness |
| `IMPLEMENTATION_STATUS.md` | Living Exists/Specified/Demonstrated/Validated/Production status across programs A–M |

The public website and `milexium.com` infrastructure are owned by Chris and live
outside this repository. This repository is the product, data, modeling, and
technical-evidence workspace; it intentionally contains no deployable website.

Large raw files, resumable checkpoints, trained models, predictions, outreach
drafts, and credentials are local-only and gitignored. The storage contract is
documented in [knowledge/docs/DATA_STORAGE.md](knowledge/docs/DATA_STORAGE.md).

## Start here

- [Implementation status](IMPLEMENTATION_STATUS.md) — what's built across programs A–M
- [Documentation index](knowledge/docs/README.md)
- [Master roadmap](knowledge/docs/MASTER_ROADMAP.md)
- [Competitive positioning](knowledge/docs/COMPETITIVE_POSITIONING.md)
- [Data source catalog](knowledge/docs/DATA_SOURCES.md)
- [Project journal](knowledge/docs/JOURNAL.md)
- [YC application draft](knowledge/docs/yc/application-draft.md)

Run the platform test suite with `py -3 -m pytest app/ evidence/conformance/`, and
the SDK quickstart with `py -3 -m app.sdk.example`.

Run `py -3 platform/tools/audit_repository.py` after fetches, file moves, or model runs to
check repository structure, ignored-data boundaries, panel schemas, duplicate
keys, checkpoint continuity, and raw Parquet file integrity.
