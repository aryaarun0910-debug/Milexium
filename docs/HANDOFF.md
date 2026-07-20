# TransitPulse session handoff

Read this first. It is the complete state of the project as of Sunday 20 July 2026, written for a fresh Claude Code session working in this repo.

## What TransitPulse is

Explainable scheduling and demand prediction for US paratransit and NEMT operators. Two founders: Arya Arun (ML, data, backend; this machine's user) and Chris Legge (product, frontend). Spun out of their EWB UK Engineering for People Design Challenge project (Grand Final, top 36 of ~13,000 students, demand-predictive bus routing for Ladywood, Birmingham). Source repo: https://github.com/ChrisLegge/ewb_bus_routing_project. This repo: https://github.com/aryaarun0910-debug/TransitPulse (private, Arya's account).

Goal: submit a YC application by Friday 25 July 2026. Everything this week serves that.

## Locked strategy decisions (do not relitigate)

From a prior grill session (see YC_APPLICATION_NOTES.md) plus decisions made 20 July:

1. Beachhead customer: paratransit (ADA complementary) and NEMT operators, US-first. NOT fixed-route agencies, NOT transport hubs. Statutory funding, compliance-heavy, opaque incumbents (Ecolane, TripSpark, RouteMatch/Uber Health).
2. Wedge: explainability and audit trail, not model sophistication. "Every trip, explained." Every scheduling decision and every denial carries human-readable factors and rejected alternatives.
3. Expansion story (for the YC vision section only, not the build): same explainable routing engine later serves campus shuttles, airport landside, hub circulators, small fixed-route agencies. An earlier hub/mismatch-score self-serve website concept was deliberately demoted to phase 2; do not resurrect it as the current product.
4. FPGA/hardware: cut from product. Founder-story credential only. Never propose FPGA inference; the workload is milliseconds on CPU and it reads as complexity without judgment.
5. Two founders only (Jack Booth is not part of TransitPulse). Equity split and CEO-on-the-form must be settled by Tue 22 July.
6. Model sophistication is not the blocker; customer contact is. Outreach runs in parallel with, never after, engineering.
7. The website IS a credibility page (for outreach recipients and YC readers), not a self-serve demo. No public map demo: paratransit is door-to-door and PHI-adjacent.

## Operating directives from Arya

- Ambition level: do NOT scope work to "what fits in 5 days by hand." With Claude doing the coding and data retrieval, target roughly a year of founder output this week: real public data pulled and analyzed, personalized outreach at scale, complete application drafts, working software. Bias to building and fetching real data over describing what could be built.
- Style, everywhere (prose, commits, docs): no emojis, no em dashes, no AI cliches. Plain commas, periods, parentheses, colons.
- AI attribution on commits is fine (rule updated 20 July 2026: Arya said he does not mind it, Claude is part of the team). The no-emoji and no-em-dash rules still stand.
- The EWB result appears as a single credential line wherever mentioned, never the identity.

## Repo state (all committed and pushed to main)

- README.md: company positioning, founders, structure
- YC_APPLICATION_NOTES.md, cold_outreach_template.md, outreach_target_list.md: Arya's pre-existing working notes (CTAA email is Tier 1 outreach; template exists; targets listed by tier)
- docs/yc-plan-jul25.md: day-by-day plan to submission (see below)
- docs/website-brief.md: Chris's complete first-pass website brief (paratransit credibility site, definition of done, he builds in web/ which does not exist yet)
- docs/demo-assets/: 5 committed PNGs (why_this_trip, capacity_alert, why_this_forecast, demand_curve, fleet_timeline), rendered marketing screenshots
- pipeline/: the v1 synthetic pipeline, run in this order:
  - generate_trips.py: 12 months synthetic county paratransit bookings (~90k, 245/day), anchored to NTD demand-response norms (subscription dialysis MWF/TTS cohorts, day program, medical purpose mix, midday peaks, weather-sensitive cancellations, seed 42)
  - train_demand.py: zone-hour XGBoost (count:poisson), strict 90-day temporal holdout. R2 0.839 vs seasonal-naive 0.817; RMSE 0.434 vs 0.463. Always report against the naive baseline; that honesty is deliberate and must be preserved.
  - schedule_trips.py: one service day (Tue 2026-04-14): hub pooling (dialysis/day-program/medical zones, runs of up to 5 riders within 30 min) then greedy assignment across 20 vehicles in 4 shift bands. 229/253 placed, 77% pooled, deadhead 17% of drive. Every assignment/denial logged to output/audit_log.json with factors and rejected alternatives. ADA 49 CFR 37.131(b)(2) one-hour negotiation window is used for demand trips; standing orders get +45 min.
  - make_demo_assets.py: renders the 5 PNGs (palette: blue #2a78d6 accent, validated reference set)
  - pipeline/output/ is gitignored (regenerate by running the scripts)
- pipeline/README.md: run order, current numbers, and an honesty-notes section (synthetic-data caveat, greedy-v1 caveat, the alert card's "suggested action" line is illustrative not computed, no PHI exists, real product must be HIPAA-aware)

Environment: Windows 11, Python 3.14 via `py -3`, xgboost 3.2.0, pandas 3.0.0, sklearn 1.8.0, shap 0.52.0, matplotlib 3.10.8 all installed. GitHub CLI authed as aryaarun0910-debug.

## The plan (docs/yc-plan-jul25.md), status as of Sun 20 July

- Sun 20: repo + pipeline + demo assets DONE. Still open today: Arya registers domain, queues CTAA + Tier 2 outreach for Mon 8-9am US Eastern, confirms Chris's GitHub username for the collaborator invite.
- Mon 21: outreach wave 1 out; wave 2 list built; Chris site skeleton live on Vercel; tracking sheet started.
- Tue 22: outreach wave 2; full YC application draft (docs/yc-application-draft.md, does not exist yet); equity/CEO settled.
- Wed 23: 60-90s product demo video recorded over the demo assets; website hits definition of done; EWB IP terms checked (YC asks about encumbrances).
- Thu 24: 1-minute founder video; grill pass on the application; fold in customer-call learnings.
- Fri 25: final review, submit in the morning UK time, then wave 3 outreach.

## Upgraded scope (the "year in 5 days" additions, in priority order)

These are additions the next session should drive, beyond the base plan:

1. NTD data pull (highest value): download the FTA National Transit Database demand-response tables (service, expenses, ridership per agency). Build a per-agency economics table: trips/year, cost/trip, revenue hours. Use it to (a) size the market bottom-up for the application, (b) personalize outreach ("your agency reported N trips at $X/trip in NTD 2024; a 10% deadhead cut is worth $Y") for 50+ targets instead of the current 6.
2. Expand the outreach target list to 50+ using NTD agency lists + CTAA membership + state DOT paratransit directories, each row with a personalization hook.
3. Draft every YC application answer including the vision/expansion section (paratransit beachhead, then campus/hub/small fixed-route with the same engine).
4. Conformal prediction intervals on the demand model (split-conformal, about a half day) so forecasts read "16 to 21 bookings expected" with calibrated coverage; almost nobody in this market ships honest uncertainty.
5. /method page content for the website with real citations (NTD norms, 49 CFR 37.131, model card).
6. If time remains: counterfactual backtest (proposed vs actual allocation on a replayed synthetic month) and a computed version of the capacity-alert suggested action.

Known constraint no ambition changes: outreach reply latency is human. Send early, send wide, personalize with data.

## Key numbers memorized for copy (source: pipeline runs above, all synthetic)

R2 0.839 vs 0.817 naive (temporal holdout); 229/253 requests placed; 77% shared runs; deadhead 17% of drive time; every decision explained. EWB credential: Grand Final, top 36 of ~13,000 students. Do not reuse EWB's 0.94 R2 for TransitPulse's pipeline; that number belongs to the Ladywood model and the two must never be conflated.
