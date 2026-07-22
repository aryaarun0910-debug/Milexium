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

| Path | Purpose |
|---|---|
| `realdata/` | Public-data ingestion, derived demand panels, model training, evaluation, and compact evidence outputs |
| `ntd/` | FTA National Transit Database economics, market sizing, and outreach inputs |
| `reference_agency/` | Fictional, synthetic trip-level agency used only for scheduler and audit-trail demonstrations |
| `kaggle/` | GPU notebook and recorded transformer experiment results |
| `outreach/` | Design-partner research, templates, target tables, and locally ignored drafts |
| `docs/` | Active roadmap, source catalog, research questions, journal, and YC draft |
| `artifacts/` | Curated generated screenshots and dated knowledge-graph snapshots |
| `tools/` | Repository and data integrity checks |

The public website and `milexium.com` infrastructure are owned by Chris and live
outside this repository. This repository is the product, data, modeling, and
technical-evidence workspace; it intentionally contains no deployable website.

Large raw files, resumable checkpoints, trained models, predictions, outreach
drafts, and credentials are local-only and gitignored. The storage contract is
documented in [docs/DATA_STORAGE.md](docs/DATA_STORAGE.md).

## Start here

- [Documentation index](docs/README.md)
- [Master roadmap](docs/MASTER_ROADMAP.md)
- [Competitive positioning](docs/COMPETITIVE_POSITIONING.md)
- [Data source catalog](docs/DATA_SOURCES.md)
- [Project journal](docs/JOURNAL.md)
- [YC application draft](docs/yc/application-draft.md)

Run `py -3 tools/audit_repository.py` after fetches, file moves, or model runs to
check repository structure, ignored-data boundaries, panel schemas, duplicate
keys, checkpoint continuity, and raw Parquet file integrity.
