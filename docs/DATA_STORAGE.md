# Data storage contract

TransitPulse has roughly 56 GB of local research data. Moving it merely for a
prettier tree would create unnecessary corruption and path risk, so the existing
physical locations are retained and governed by the rules below.

## Storage tiers

| Tier | Location | Git policy | Contents |
|---|---|---|---|
| Raw immutable | `realdata/raw_tlc/`, `realdata/raw_tlc_taxi/` | Ignored | Monthly source Parquet files downloaded from NYC TLC |
| Resumable checkpoints | `realdata/panels/*_monthly/` | Ignored | One server-aggregated CSV per source month; current months use `.partial.csv` |
| Compact reproducibility panels | `realdata/panels/` | Selectively tracked | AAR, nationwide NTD monthly, and weather panels small enough to reproduce public claims |
| Large derived panels | `realdata/panels/` | Ignored | Chicago, MTA bus/subway, and full TLC zone-hour panels regenerated from fetchers/checkpoints |
| Model outputs | `realdata/output/` | Ignored | Serialized models and row-level validation predictions |
| Published metrics | `realdata/*.json`, `kaggle/results/` | Tracked | Small evaluation summaries and explanation examples |
| Reference agency outputs | `reference_agency/output/` | Ignored | Synthetic trips, schedules, models, and audit logs |
| Outreach drafts | `outreach/drafts/` | Ignored | Generated recipient-specific email drafts |
| Curated artifacts | `artifacts/` | Tracked by exception | Demo screenshots and dated knowledge-graph snapshots |
| Credentials | `.env`, `.env.*` | Ignored | API tokens and local configuration; never data provenance |

## Invariants

- Raw source files are never edited in place. A bad file is removed and fetched again.
- A finalized monthly checkpoint represents a complete calendar month. In-progress
  months use `YYYY-MM.partial.csv` and may be refreshed.
- Derived panels have a documented unique key and are checked for duplicates.
- Missing source periods remain missing and documented; they are never silently
  converted into zero observations.
- Every tracked dataset has a public source and regeneration script in
  [DATA_SOURCES.md](DATA_SOURCES.md).
- Generated model binaries and row-level predictions remain outside Git; compact
  metrics required for claims remain tracked.

## Integrity check

Run:

```powershell
py -3 tools/audit_repository.py
```

The command checks structural boundaries, Git ignore coverage, raw Parquet magic
bytes and month continuity, checkpoint continuity, CSV schemas, duplicate keys,
date coverage, and aggregate totals. It exits non-zero on a blocking integrity
failure.
