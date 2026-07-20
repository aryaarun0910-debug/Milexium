# TransitPulse

Explainable scheduling and demand prediction for US paratransit and NEMT operators.

Paratransit is a statutory duty (ADA complementary paratransit, Medicaid NEMT) run on opaque legacy dispatch software. Operators cannot see why the system scheduled a trip the way it did, which makes compliance reporting painful and makes bad routing impossible to challenge. TransitPulse predicts demand and schedules trips with a full audit trail: every routing decision comes with a human-readable explanation of why.

## Why us

We built a demand-predictive routing system on real transit data (0.94 R2 demand model with temporal validation, 1.16% mean routing optimality gap, SHAP-based explainability, benchmarked against ARIMA and deep learning baselines) that reached the Grand Final of a 13,000-student international engineering competition. The explainability layer was built first, not bolted on.

## Founders

- Arya Arun: ML, demand modeling, optimization, backend
- Chris Legge: product, frontend, embedded systems

## Structure

- `ntd/` FTA National Transit Database pulls: the full US demand-response market, per-agency economics, market sizing, outreach personalization
- `realdata/` real demand data (NYC Access-A-Ride, Chicago TNP, NYC TLC) and real-data demand models with conformal intervals
- `kaggle/` GPU-scale training packages (transformer on the 1B+ trip TLC corpus)
- `outreach/` generated target lists with per-agency hooks
- `pipeline/` v1 synthetic pipeline (to be retired once real data covers everything it demonstrates)
- `web/` marketing and demo site (React + TypeScript + Vite, not started)
- `docs/` briefs, plans, decisions, and the project journal

## Working docs

- [docs/JOURNAL.md](docs/JOURNAL.md) — running journal: what was added, when, and why
- [docs/yc-plan-jul25.md](docs/yc-plan-jul25.md) — execution backlog for the 25 July YC deadline
- [docs/website-brief.md](docs/website-brief.md) — website first-pass brief for Chris
- [YC_APPLICATION_NOTES.md](YC_APPLICATION_NOTES.md) — locked strategy decisions
- [outreach_target_list.md](outreach_target_list.md) + [cold_outreach_template.md](cold_outreach_template.md) — customer discovery
