# Milexium

Explainable demand forecasting and scheduling support for US paratransit and
NEMT operators. Every mile, justified (tagline, tentative). Milexium is being
built around a simple operational promise: every forecast, scheduling
recommendation, rejection, and human override should be reviewable after the
fact.

The production model recommendation is deliberately conventional: XGBoost beat
the experimental transformer on the same real Access-A-Ride holdout, so the tree
model remains the reference implementation. See [realdata/README.md](realdata/README.md)
for the full comparison and limitations.

## Repository map

The repository has two layers. The **product & evidence workspace** is the
original real-data forecasting, market-sizing, and demonstration work. The
**expansion platform** is the contract-driven runtime being built per the
`Milexium Expansion plan` blueprint — see
[`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md) for what is actually
Exists vs. Specified in each program.

### Product & evidence workspace

| Path | Purpose |
|---|---|
| `realdata/` | Public-data ingestion, derived demand panels, model training, evaluation, and compact evidence outputs |
| `ntd/` | FTA National Transit Database economics, market sizing, and outreach inputs |
| `reference_agency/` | Fictional, synthetic trip-level agency used only for scheduler and audit-trail demonstrations |
| `kaggle/` | GPU notebook + recorded transformer experiment — kept **negative-result evidence** (XGBoost beat it; cited in `docs/MODEL_CARDS.md`), not dead code |
| `outreach/` | Design-partner pitch, cold-email templates, target tables (drafts locally gitignored) — the shadow-mode-pilot toolkit |
| `docs/` | Roadmap, source catalog, model cards, research questions, journal, YC draft |
| `artifacts/` | Curated generated screenshots and dated knowledge-graph snapshots |
| `tools/` | Repository and data integrity checks |

### Expansion platform (the transport decision runtime)

| Path | Purpose |
|---|---|
| `packages/` | One package per program: `canonical` (A), `connect` (B), `estate` (C data layer), `core` (D), `forecast` (E), `verify` (G), `evidence` (I), `sdk` (M) |
| `architecture/` | ADRs (`decisions/`), normative contracts, threat models, formal specs |
| `conformance/` | Executable proof: fixtures, property tests, adversarial tests (the evidence behind every "Exists"/"Demonstrated" claim) |
| `data/` | Governed 250 GB estate — `catalog/` (committed manifests + rights) with gitignored raw/derived zones; acquire via `packages/estate` |
| `workstreams/` | Work packets + the `DOSSIER_COVERAGE.md` 80-tech/72-project ledger |
| `benchmarks/`, `research/`, `third_party/`, `ops/` | Perf/quality benchmarks, experiment records, the vendoring gate, and ops readiness |
| `IMPLEMENTATION_STATUS.md` | Living Exists/Specified/Demonstrated/Validated/Production status across programs A–M |

The public website and `milexium.com` infrastructure are owned by Chris and live
outside this repository. This repository is the product, data, modeling, and
technical-evidence workspace; it intentionally contains no deployable website.

Large raw files, resumable checkpoints, trained models, predictions, outreach
drafts, and credentials are local-only and gitignored. The storage contract is
documented in [docs/DATA_STORAGE.md](docs/DATA_STORAGE.md).

## Start here

- [Implementation status](IMPLEMENTATION_STATUS.md) — what's built across programs A–M
- [Documentation index](docs/README.md)
- [Master roadmap](docs/MASTER_ROADMAP.md)
- [Competitive positioning](docs/COMPETITIVE_POSITIONING.md)
- [Data source catalog](docs/DATA_SOURCES.md)
- [Project journal](docs/JOURNAL.md)
- [YC application draft](docs/yc/application-draft.md)

Run the platform test suite with `py -3 -m pytest packages/ conformance/`, and
the SDK quickstart with `py -3 -m packages.sdk.example`.

Run `py -3 tools/audit_repository.py` after fetches, file moves, or model runs to
check repository structure, ignored-data boundaries, panel schemas, duplicate
keys, checkpoint continuity, and raw Parquet file integrity.
