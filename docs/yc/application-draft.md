# YC application draft

First full draft. Written against the stable, publicly-documented standard YC question set (confirmed against two independent current guides, since the live form at apply.ycombinator.com/home is behind login and couldn't be fetched directly) — **check the actual live form for exact current wording/order before submitting**, but the substance below should transfer directly.

Style: direct, decisions stated, tradeoffs owned, no hedging, no filler. Historical strategy context is archived in `docs/archive/2026-07-yc-application-notes.md`; current work is governed by `docs/MASTER_ROADMAP.md`. Every number below must trace to a script or evidence artifact in this repository.

Anywhere you see `[ARYA/CHRIS: ...]`, that's personal/biographical content I don't have and won't invent. Fill those in, then run `/grill-me` against the whole thing before submission.

---

## Company

**Company name:** TransitPulse

**Describe what your company does in 50 characters or less:**
Explainable dispatch software for paratransit.

**Company URL:** https://transitpulse-psi.vercel.app

**What is your company going to make?**
Software that predicts paratransit and NEMT demand and schedules trips with a full audit trail — every assignment and every denial comes with the exact factors that drove it and the alternatives that were rejected, with reasons. Paratransit (ADA-mandated door-to-door transit) and NEMT (Medicaid non-emergency medical transport) run on decades-old dispatch software from vendors like Ecolane, TripSpark, and RouteMatch/Uber Health that gives agencies no visibility into why the system made a scheduling decision. That's a real problem because these agencies are compliance-heavy: they get audited on missed trips, late pickups, denials, and negotiated pickup windows (49 CFR Part 37), and right now most of them can't produce a clean answer to "why was this trip denied" without manually reconstructing it. We give them that answer automatically, plus a demand forecast so they can staff ahead of it instead of reacting to it.

---

## Progress

**How far along are you?**
Pre-revenue, pre-pilot. What exists: a demand-forecasting model validated on real ridership data from two cities (not synthetic — see below), a working scheduler with a structured, rule-based audit trail (not an LLM-generated explanation; every denial reason is a deterministic code derived from the actual constraint that failed), and a bottom-up market analysis built from every US demand-response operator's own federal filings.

**Do you have revenue? Do you have any users?**
No revenue, no pilot customers yet. Outreach to `[N — see outreach/targets_ntd.csv, currently 80 tiered targets]` paratransit agencies and NEMT brokers is in progress as of this application. `[ARYA/CHRIS: update this line with actual reply/call count once outreach has run — do not submit with a stale number]`

**What have you built, concretely?**
- A demand model validated on 26.3 million real NYC Access-A-Ride bookings (the largest paratransit operation in the US): R2 0.986 against a seasonal-naive baseline of 0.923, on a strict 90-day holdout the model never saw during training or tuning [realdata/metrics_real.json]. The same recipe, unmodified, gets R2 0.966 vs 0.936 naive on a second real city (Chicago, 4.6M training rows, 77 zones) [realdata/metrics_real.json] - the point isn't either number alone, it's that the approach generalizes.
- A four-fold rolling-origin backtest (not a single lucky holdout window): R2 0.972 mean across folds including a materially harder winter fold, still beating naive [realdata/backtest_aar.json].
- Calibrated uncertainty, not just point forecasts: split-conformal prediction intervals, so a capacity-planning answer reads "16 to 21 bookings expected," not a bare number pretending to be exact.
- A rule-based scheduler that pools shared rides to common destinations (dialysis centers, day programs) and produces a structured reason code for every rejected vehicle assignment (`NO_ACCESSIBLE_CAPACITY`, `NEGOTIATION_WINDOW`, `SHIFT_END`) — deterministic and auditable, never an LLM explanation standing in for the actual decision logic.
- A bottom-up market map: pulled and joined the FTA National Transit Database filings for every US demand-response operator (1,920 agencies, 2024 report year): $7.06B in combined annual operating expense, 139.7M annual trips, median $37.97 cost per trip, 17.3% of vehicle-hours spent deadheading [ntd/market_sizing.md]. That last number alone is worth roughly $94M/year in aggregate if cut by just 10% across the agencies that report it.

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
Bottom-up, not top-down: $7.06B in annual US demand-response operating expense across 1,920 NTD-reporting agencies in 2024, 139.7M annual trips [ntd/market_sizing.md, pulled directly from FTA filings]. We are not selling against that whole number — we're selling software that captures a fraction of the savings and compliance-risk-reduction it creates, and we say so explicitly rather than implying we're addressing the whole opex line. NEMT (Medicaid-funded non-emergency medical transport) is a substantially larger adjacent market we have not yet sized bottom-up the same way; that's a next step, not a claimed number.

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

Grand Final, top 36 of roughly 13,000 students, Engineers Without Borders UK Engineering for People Design Challenge — a demand-predictive bus-routing system for Ladywood, Birmingham (source repo: github.com/ChrisLegge/ewb_bus_routing_project). That project's R2 0.94 and other headline numbers belong to that system and that dataset; they are never to be quoted as TransitPulse's numbers. TransitPulse's own numbers (above) are lower and come from different, real data — reported that way on purpose. This is a single credential line establishing the team can ship real ML/optimization work under a deadline, not a claim that the two systems are the same thing.

**IP check:** `[ARYA/CHRIS: confirm the EWB competition terms and disclose any IP encumbrance before submitting.]`

---

## Vision (expansion section)

Paratransit and NEMT are the beachhead because they're compliance-heavy and statutorily funded — real budgets, forced-hand buying trigger, slow-moving incumbents. The same explainable demand-and-scheduling engine generalizes to any operation where "why did the system decide this" matters and isn't currently answerable: campus shuttle systems, airport landside operations, hub/circulator routes, and small fixed-route agencies too small to run their own optimization team. We are deliberately not building or pitching that expansion now — it would dilute the actual near-term sell — but the underlying forecasting-plus-audit-trail architecture doesn't change, only the zone/vehicle/policy configuration does, which we've already validated works across different real cities and different transit modalities (paratransit, rideshare-scale demand in two cities, real fare-payment ridership) without touching the core recipe.

---

## Curious

**What convinced you to apply to YC? How did you hear about it?**
`[ARYA/CHRIS: fill in]`

**Anything else we should know?**
`[ARYA/CHRIS: optional — a good use of this slot, if true, is a one-line status update on outreach replies/calls booked, since "traction since we wrote the main answers" is a legitimate thing to add here right before submission]`
