# YC application draft

First full draft. Written against the stable, publicly-documented standard YC question set (confirmed against two independent current guides, since the live form at apply.ycombinator.com/home is behind login and couldn't be fetched directly) — **check the actual live form for exact current wording/order before submitting**, but the substance below should transfer directly.

Style: direct, decisions stated, tradeoffs owned, no hedging, no filler. Historical strategy context is archived in `docs/archive/2026-07-yc-application-notes.md`; current work is governed by `docs/MASTER_ROADMAP.md`. Every number below must trace to a script or evidence artifact in this repository.

**Status language is binding here.** This repository uses one status vocabulary — **Exists / Specified / Demonstrated / Validated / Production** (ADR-0001) — and **Validated requires consented operator data against a declared baseline**. Milexium has none: zero customers, zero pilots, zero operator data. Nothing in this draft may say *validated*, *proven*, *guaranteed*, or quote a savings figure the repository cannot re-derive. See the standing rule in `docs/COMPETITIVE_POSITIONING.md`.

Anywhere you see `[ARYA/CHRIS: ...]`, that's personal/biographical content I don't have and won't invent. Fill those in, then run `/grill-me` against the whole thing before submission.

---

## Company

**Company name:** Milexium

**Tagline (tentative, confirm before submitting):** Every mile, justified.

**Describe what your company does in 50 characters or less:**
Explainable dispatch software for paratransit.

**Company URL:** https://milexium.com

**What is your company going to make?**
Software that predicts paratransit and NEMT demand and schedules trips with a full audit trail — every assignment and denial *our* system makes carries the exact constraint that produced it and the alternatives it rejected, with reasons. Where the decision was the incumbent's, we record the reason as **unknown** rather than inventing a plausible one; that refusal is the product working, not a hole in it. Paratransit (ADA-mandated door-to-door transit) and NEMT (Medicaid non-emergency medical transport) run on decades-old dispatch software from vendors like Ecolane, TripSpark, and RouteMatch/Uber Health that gives agencies no visibility into why the system made a scheduling decision. That's a real problem because these agencies are compliance-heavy: they get audited on missed trips, late pickups, denials, and negotiated pickup windows (49 CFR Part 37), and right now most of them can't produce a clean answer to "why was this trip denied" without manually reconstructing it. We give them that answer automatically, plus a demand forecast so they can staff ahead of it instead of reacting to it.

---

## Progress

**How far along are you?**
Pre-revenue, pre-pilot. What exists: a demand-forecasting model demonstrated on real public ridership data from two cities (not synthetic — see below), a working scheduler with a structured, rule-based audit trail (not an LLM-generated explanation; every denial reason is a deterministic code derived from the actual constraint that failed), and a bottom-up market analysis built from every US demand-response operator's own federal filings.

One thing we want to be exact about, because you will find it anyway: all of that is **demonstrated on public data, not validated on an operator's**. In our own status vocabulary the word *validated* is reserved for a result on consented operator data against a declared baseline, and we have no such data. Public aggregate filings can demonstrate a forecasting task; they cannot validate capacity planning, scheduling, denial explanation, or an economic impact claim. Every number below is labelled accordingly.

**Do you have revenue? Do you have any users?**
No revenue, no pilot customers yet. Outreach to `[N — see outreach/targets_ntd.csv, currently 80 tiered targets]` paratransit agencies and NEMT brokers is in progress as of this application. `[ARYA/CHRIS: update this line with actual reply/call count once outreach has run — do not submit with a stale number]`

**What have you built, concretely?**
- A demand model demonstrated on 26.3 million real NYC Access-A-Ride bookings (the largest paratransit operation in the US): R2 0.986 against a seasonal-naive baseline of 0.923, on a strict 90-day holdout the model never saw during training or tuning [realdata/metrics_real.json]. The same recipe, unmodified, gets R2 0.966 vs 0.936 naive on a second real city (Chicago, 4.6M training rows, 77 zones) [realdata/metrics_real.json] - the point isn't either number alone, it's that the approach generalizes. This is a public **aggregate** panel (borough-hour), so it demonstrates the forecasting task; it does not validate any operator's own dispatch, and we don't claim it does.
- A four-fold rolling-origin backtest (not a single lucky holdout window): R2 0.972 mean across folds including a materially harder winter fold, still beating naive [realdata/backtest_aar.json].
- Calibrated uncertainty, not just point forecasts: split-conformal prediction intervals, so a capacity-planning answer reads "16 to 21 bookings expected," not a bare number pretending to be exact — and the interval **withdraws its own coverage guarantee** when the serving path detects drift that contradicts exchangeability, instead of quietly continuing to publish it [ADR-0049].
- A rule-based scheduler that pools shared rides to common destinations (dialysis centers, day programs) and produces a structured reason code for every rejected vehicle assignment (`NO_ACCESSIBLE_CAPACITY`, `NEGOTIATION_WINDOW`, `SHIFT_END`) — deterministic and auditable, never an LLM explanation standing in for the actual decision logic. Alongside it, a CP-SAT solver portfolio that **reproduces the published Cordeau DARP optima at 0.00% gap against a bound we compute ourselves rather than borrow from the paper** [ADR-0060, benchmarks/optimization/portfolio_results.json]. The result we got most out of was the losing one: it showed our own previous heuristic had been 1.6–8.0% off optimal on every instance we can now prove, which nobody could have known without putting a prover next to it.
- A bottom-up market map: pulled and joined the FTA National Transit Database filings for every US demand-response operator (1,920 agencies, 2024 report year): $7.06B in combined annual operating expense, 139.7M annual trips, median $37.97 cost per trip [ntd/market_sizing.md].
- What that panel actually says. On a balanced panel of 1,606 agencies filing demand-response service in both 2015 and 2024, cost per trip went from **$29.19 to $51.70 — +77% nominal, +34% real** against CPI-U. About 81% of the rise is the price of an hour of service and about 19% is delivering fewer trips per hour, and only the second is anything a scheduler touches [outreach/panel_findings.json, `dr_cost_growth_split_2015_2024`]. Every figure in that file cleared a gate that rejected 8 of 17 candidate findings and publishes the rejections with the measurement that killed each one.
- The strongest lead we have, at its true strength and no further. Among the 355 operators filing passenger miles in both years, **occupancy — passenger miles per vehicle mile — fell 10.0%, 1.213 to 1.092, while trips got *shorter* (−4.6%)**; 66.8% of those agencies lost occupancy and the recovery has stalled [research/h5e_ridesharing.json]. So the productivity collapse is lost ride-sharing, not longer rides. That matters because trip length is demand geography and a scheduler cannot change it, whereas occupancy is precisely what a scheduler determines. The caveat we lead with rather than bury: passenger-mile filing is a Full Reporter obligation, so those 355 are a non-random **26% of the panel by agency count, though 66% of its trips**. We therefore scope this to larger operators and call it a hypothesis to test in shadow mode, not a sector result and not a savings number.
- A claim we killed, which is the one we would most have liked to keep. Our original pitch was deadhead — 17.3% of demand-response vehicle-hours run empty, so cut it. We then tested whether an agency's deadhead share predicts what its trips cost. It does not: **Pearson +0.017 against log cost per trip, OLS R² 0.0003, n=405** [research/h5b_structure_vs_cost.py], and median cost per trip is flat across deadhead quartiles ($48.53 in the lowest, $54.09 in the highest — too small to lead with and the wrong way round to be a lever) [outreach/panel_findings.json, ADR-0058]. Empty movement still costs money, but this panel cannot identify which of it is avoidable or what a marginal hour is worth, so we deleted the headline opportunity figure that analysis was carrying instead of restating it more softly. Our own teardown code already refused to print a savings envelope without an operator's fixed/variable cost split; the sales copy had to catch up with the engineering.
- The assurance work, because it is the part that will still be true in a year: **2,337 passing tests**; an evidence pack with a **standalone verifier that re-derives every claim from the primitive rows the pack carries and runs in an interpreter that cannot import Milexium at all** [ADR-0066]; and a one-command demo — messy operator-style export → PII quarantine → graduated repair → canonical records → a scheduling decision with its reasons → deadhead teardown → serve-time drift → an evidence pack that re-verifies itself across 76 checks with zero mismatches — that runs in **2.5 seconds** and whose six best moments are all refusals [ADR-0068]. It ends on the line "Demonstrated. Not Validated. No customers, no pilots, no operator data."

---

## Idea

**Why did you pick this idea?**
`[ARYA/CHRIS: this is a "why you specifically" question, not a market-logic question — YC wants the personal thread. Draft direction: connects to the EWB Ladywood project (see below), and to whatever personal motivation led you toward transit/accessibility specifically. Write this yourselves; don't let a market-sizing argument stand in for a personal answer here.]`

**What's new about what you're making? Why hasn't an incumbent done this?**
The incumbents (Ecolane, TripSpark, RouteMatch/Uber Health) are 15-20-year-old dispatch platforms built before "explainability" was a category anyone asked for. Their optimization is a black box even to the agencies running it — when a rider or a state auditor asks "why was this trip denied," the honest answer at most agencies today is "someone has to go dig through logs." We built the audit trail as the actual product, not a feature bolted onto a routing algorithm afterward: every scheduling decision is deterministic and traceable back to the specific constraint that produced it, in a format an agency can hand to an auditor or a grievance hearing without translation. That is a genuinely different starting point than "we have a smarter model," and it's why we didn't chase a bigger model this week when we had the chance to — see the technical-depth evidence above, which exists specifically to demonstrate engineering seriousness, not because "bigger" was the actual product bet.

**Who are your competitors, and what do you understand that they don't?**
Ecolane, TripSpark, and RouteMatch/Uber Health are incumbent dispatch vendors;
NEMT brokers such as Modivcare and MTM may be channel partners or competitors.
What we understand that a generic "AI for transit" competitor would miss is that
forecast accuracy alone does not cause an agency to replace operational software.
The initial product must fit around the incumbent workflow and make decisions,
overrides, denials, and performance evidence reviewable.

**How do you/will you make money?**
`[ARYA/CHRIS: pricing model not yet locked — per-vehicle/month SaaS is the obvious default for this market (matches how Ecolane/TripSpark are typically priced), but confirm before submitting. Do not leave this blank; YC penalizes vagueness on monetization more than an imperfect-but-stated model.]`

**Market size — how big is this?**
Bottom-up, not top-down: $7.06B in annual US demand-response operating expense across 1,920 NTD-reporting agencies in 2024, 139.7M annual trips [ntd/market_sizing.md, pulled directly from FTA filings]. The reason this is a market now rather than a permanent condition is the direction of travel: on the balanced 1,606-agency panel, the real cost of a demand-response trip rose **34% above inflation** between 2015 and 2024 while agencies carried fewer riders per hour [outreach/panel_findings.json]. That is a budget line growing faster than the funding behind it, at operators who are statutorily obliged to keep serving.

We are not selling against the $7.06B. We are selling a subscription to the evidence and capacity layer, and we deliberately do **not** quote a percentage of it as recoverable savings — we have no operator data to estimate one from, and the last savings figure we did quote turned out to rest on a relationship that does not exist in the data (see the deadhead item above). NEMT (Medicaid-funded non-emergency medical transport) is a substantially larger adjacent market we have not yet sized bottom-up the same way; that's a next step, not a claimed number.

---

## Team

**Founders:**
- Arya Arun — ML, demand modeling, data engineering, backend. `[ARYA: add location, visa status, and full-time/part-time status]`
- Chris Legge — product, frontend, embedded systems. `[CHRIS: same as above]`

**How did you meet, and how long have you known each other?**
`[ARYA/CHRIS: fill in]`

**Please tell us about a time you successfully hacked (in the positive sense) some non-computer system to your advantage.**
`[ARYA/CHRIS: this is a real, standard YC question and it wants a genuine personal anecdote, not a company achievement — do not substitute the EWB project here unless the anecdote is specifically about creatively working around a constraint, not just "we built good software on a deadline."]`

**Have any of the founders committed a crime, been expelled, or been sued?**
`[ARYA/CHRIS: answer honestly, standard YC disclosure question]`

**Equity split and who is CEO on the form:**
`[ARYA/CHRIS: settle the equity split and CEO before submission. Do not submit this answer unresolved.]`

**Where do you live now, and where will the company be based?**
`[ARYA/CHRIS: state current UK locations, visa status, and willingness to relocate plainly.]`

---

## Credential / evidence line (use once, don't oversell)

Grand Final, top 36 of roughly 13,000 students, Engineers Without Borders UK Engineering for People Design Challenge — a demand-predictive bus-routing system for Ladywood, Birmingham (source repo: github.com/ChrisLegge/ewb_bus_routing_project). That project's R2 0.94 and other headline numbers belong to that system and that dataset; they are never to be quoted as Milexium's numbers. Milexium's own numbers (above) are lower and come from different, real data — reported that way on purpose. This is a single credential line establishing the team can ship real ML/optimization work under a deadline, not a claim that the two systems are the same thing.

**IP check:** `[ARYA/CHRIS: confirm the EWB competition terms and disclose any IP encumbrance before submitting.]`

---

## Vision (expansion section)

Paratransit and NEMT are the beachhead because they're compliance-heavy and statutorily funded — real budgets, forced-hand buying trigger, slow-moving incumbents. The same explainable demand-and-scheduling engine generalizes to any operation where "why did the system decide this" matters and isn't currently answerable: campus shuttle systems, airport landside operations, hub/circulator routes, and small fixed-route agencies too small to run their own optimization team. We are deliberately not building or pitching that expansion now — it would dilute the actual near-term sell — but the underlying forecasting-plus-audit-trail architecture doesn't change, only the zone/vehicle/policy configuration does. We have **demonstrated** that portability on four different real public datasets spanning paratransit, door-to-door rideshare, and fixed-route bus and subway ridership — NYC Access-A-Ride bookings, Chicago TNP trips, and MTA bus and subway fare payments — with the same unmodified recipe beating a seasonal-naive baseline on all four [docs/MODEL_CARDS.md, realdata/metrics_real.json]. What that shows is that the configuration surface is real, not that the architecture is validated for any of those operations: none of the four is an operator running our software, and portability across public panels is not the same evidence as portability across operators.

---

## Curious

**What convinced you to apply to YC? How did you hear about it?**
`[ARYA/CHRIS: fill in]`

**Anything else we should know?**
`[ARYA/CHRIS: optional — a good use of this slot, if true, is a one-line status update on outreach replies/calls booked, since "traction since we wrote the main answers" is a legitimate thing to add here right before submission]`
