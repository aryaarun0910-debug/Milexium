# TransitPulse

Explainable scheduling and demand prediction for US paratransit and NEMT operators.

Paratransit is a statutory duty (ADA complementary paratransit, Medicaid NEMT) run on opaque legacy dispatch software. Operators cannot see why the system scheduled a trip the way it did, which makes compliance reporting painful and makes bad routing impossible to challenge. TransitPulse predicts demand and schedules trips with a full audit trail: every routing decision comes with a human-readable explanation of why.

## Why us

We built a demand-predictive routing system on real transit data (0.94 R2 demand model with temporal validation, 1.16% mean routing optimality gap, SHAP-based explainability, benchmarked against ARIMA and deep learning baselines) that reached the Grand Final of a 13,000-student international engineering competition. The explainability layer was built first, not bolted on.

## Founders

- Arya Arun: ML, demand modeling, optimization, backend
- Chris Legge: product, frontend, embedded systems

## Structure

- `web/` marketing and demo site (React + TypeScript + Vite)
- `api/` FastAPI backend
- `pipeline/` data ingestion, feature engineering, model training
- `docs/` briefs, plans, decisions

## Working docs

- [docs/yc-plan-jul25.md](docs/yc-plan-jul25.md) — submission plan for the 25 July YC deadline
- [docs/website-brief.md](docs/website-brief.md) — website first-pass brief for Chris
- [YC_APPLICATION_NOTES.md](YC_APPLICATION_NOTES.md) — locked strategy decisions
- [outreach_target_list.md](outreach_target_list.md) + [cold_outreach_template.md](cold_outreach_template.md) — customer discovery
