# TransitPulse

Demand-predictive route analysis for small US transit operators: campus shuttles, airport landside shuttles, hospital district circulators, and small city agencies.

Pick your agency in the browser, see predicted hourly rider demand painted over your actual stops, get a mismatch score showing where scheduled capacity disagrees with predicted demand, and see one optimized counterproposal with an annual dollar figure attached. No hardware, no integration: predictions come from open data alone (GTFS, weather, calendars, census, land use).

## Status

Pre-launch. First pass of the website is in progress (see [docs/website-brief.md](docs/website-brief.md)).

## Team

- Arya Arun: ML, demand modeling, data pipeline, API
- Chris Legge: website, frontend
- Jack Booth: simulation

Origin: Team LatencyZero, Engineers Without Borders UK Engineering for People Design Challenge 2025-26 (demand-predictive bus routing for Ladywood, Birmingham).

## Planned structure

- `web/` frontend (React 19 + TypeScript + Vite + MapLibre)
- `api/` FastAPI backend serving the demand model and mismatch scores
- `pipeline/` GTFS ingestion, feature engineering, model training
- `docs/` briefs, methodology, decisions
