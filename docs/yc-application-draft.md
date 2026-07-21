# YC application draft

First full draft. Written against the stable, publicly-documented standard YC question set (confirmed against two independent current guides, since the live form at apply.ycombinator.com/home is behind login and couldn't be fetched directly) — **check the actual live form for exact current wording/order before submitting**, but the substance below should transfer directly.

Style: direct, decisions stated, tradeoffs owned, no hedging, no filler. Per YC_APPLICATION_NOTES.md and the locked strategy decisions — do not relitigate those here. Every number below traces to a script in this repo; see the bracketed source.

Anywhere you see `[ARYA/CHRIS: ...]`, that's personal/biographical content I don't have and won't invent. Fill those in, then run `/grill-me` against the whole thing before submission.

---

## Company

**Company name:** TransitPulse

**Describe what your company does in 50 characters or less:**
Explainable dispatch software for paratransit.

**Company URL:** `[ARYA/CHRIS: domain not yet registered as of this draft — docs/yc-plan-jul25.md flags this as an open human-only task]`

**What is your company going to make?**
Software that predicts paratransit and NEMT demand and schedules trips with a full audit trail — every assignment and every denial comes with the exact factors that drove it and the alternatives that were rejected, with reasons. Paratransit (ADA-mandated door-to-door transit) and NEMT (Medicaid non-emergency medical transport) run on decades-old dispatch software from vendors like Ecolane, TripSpark, and RouteMatch/Uber Health that gives agencies no visibility into why the system made a scheduling decision. That's a real problem because these agencies are compliance-heavy: they get audited on missed trips, late pickups, denials, and negotiated pickup windows (49 CFR Part 37), and right now most of them can't produce a clean answer to "why was this trip denied" without manually reconstructing it. We give them that answer automatically, plus a demand forecast so they can staff ahead of it instead of reacting to it.

---

## Progress

**How far along are you?**
Pre-revenue, pre-pilot. What exists: a demand-forecasting model validated on real ridership data from two cities (not synthetic — see below), a working scheduler with a structured, rule-based audit trail (not an LLM-generated explanation; every denial reason is a deterministic code derived from the actual constraint that failed), and a bottom-up market analysis built from every US demand-response operator's own federal filings.

**Do you have revenue? Do you have any users?**
No revenue, no pilot customers yet. Outreach to `[N — see outreach/targets_ntd.csv, currently 80 tiered targets]` paratransit agencies and NEMT brokers is in progress as of this application. `[ARYA/CHRIS: update this line with actual reply/call count once outreach has run — do not submit with a stale number]`

**What have you built, concretely?**
- A demand model validated on 26.3 million real NYC Access-A-Ride bookings (the largest paratransit operation in the US): R2 0.985 against a seasonal-naive baseline of 0.923, on a strict 90-day holdout the model never saw during training or tuning [realdata/metrics_real.json]. The same recipe, unmodified, gets R2 0.966 vs 0.934 naive on a second real city (Chicago, 4.6M training rows, 77 zones) [realdata/metrics_real.json] — the point isn't either number alone, it's that the approach generalizes.
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
Ecolane, TripSpark, and RouteMatch/Uber Health are the incumbent dispatch vendors; NEMT brokers like Modivcare and MTM are a channel-partner-or-competitor question we haven't resolved yet (open item, see YC_APPLICATION_NOTES.md). What we understand that a generic "AI for transit" competitor wouldn't: this market's actual buying trigger is compliance risk, not routing efficiency. An agency doesn't switch dispatch software because the new one is 5% more efficient — it switches when an audit or a grievance exposes that it can't explain its own decisions. That reframes the sell from "better optimization" (a hard, slow sell against entrenched incumbents) to "compliance infrastructure you can't currently produce" (a forced-hand sell). It also means our forecasting sophistication, while real, is not the thing that closes a deal.

**How do you/will you make money?**
`[ARYA/CHRIS: pricing model not yet locked — per-vehicle/month SaaS is the obvious default for this market (matches how Ecolane/TripSpark are typically priced), but confirm before submitting. Do not leave this blank; YC penalizes vagueness on monetization more than an imperfect-but-stated model.]`

**Market size — how big is this?**
Bottom-up, not top-down: $7.06B in annual US demand-response operating expense across 1,920 NTD-reporting agencies in 2024, 139.7M annual trips [ntd/market_sizing.md, pulled directly from FTA filings]. We are not selling against that whole number — we're selling software that captures a fraction of the savings and compliance-risk-reduction it creates, and we say so explicitly rather than implying we're addressing the whole opex line. NEMT (Medicaid-funded non-emergency medical transport) is a substantially larger adjacent market we have not yet sized bottom-up the same way; that's a next step, not a claimed number.

---

## Team

**Founders:**
- Arya Arun — ML, demand modeling, data engineering, backend. `[ARYA: add location, visa status detail beyond what's in YC_APPLICATION_NOTES.md, and full-time/part-time status]`
- Chris Legge — product, frontend, embedded systems. `[CHRIS: same as above]`

**How did you meet, and how long have you known each other?**
`[ARYA/CHRIS: fill in]`

**Please tell us about a time you successfully hacked (in the positive sense) some non-computer system to your advantage.**
`[ARYA/CHRIS: this is a real, standard YC question and it wants a genuine personal anecdote, not a company achievement — do not substitute the EWB project here unless the anecdote is specifically about creatively working around a constraint, not just "we built good software on a deadline."]`

**Have any of the founders committed a crime, been expelled, or been sued?**
`[ARYA/CHRIS: answer honestly, standard YC disclosure question]`

**Equity split and who is CEO on the form:**
`[ARYA/CHRIS: YC_APPLICATION_NOTES.md and docs/HANDOFF.md both flag this as needing to be settled before submission and both note it wasn't settled as of when they were written — confirm this is actually locked before the form goes in. Do not submit with this unresolved; YC asks directly and vagueness here reads badly.]`

**Where do you live now, and where will the company be based?**
`[ARYA/CHRIS: fill in. YC_APPLICATION_NOTES.md notes both founders are UK-based with no US visa yet and willing to relocate — say this plainly rather than dodging it; YC has an immigration support process for accepted international teams and reads directness here as a positive, not a red flag.]`

---

## Credential / evidence line (use once, don't oversell)

Grand Final, top 36 of roughly 13,000 students, Engineers Without Borders UK Engineering for People Design Challenge — a demand-predictive bus-routing system for Ladywood, Birmingham (source repo: github.com/ChrisLegge/ewb_bus_routing_project). That project's R2 0.94 and other headline numbers belong to that system and that dataset; they are never to be quoted as TransitPulse's numbers. TransitPulse's own numbers (above) are lower and come from different, real data — reported that way on purpose. This is a single credential line establishing the team can ship real ML/optimization work under a deadline, not a claim that the two systems are the same thing.

**IP check:** `[ARYA/CHRIS: docs/yc-plan-jul25.md flags "EWB competition IP terms check" as a still-open item — YC asks about IP encumbrances directly. Confirm this before submitting, not after.]`

---

## Vision (expansion section)

Paratransit and NEMT are the beachhead because they're compliance-heavy and statutorily funded — real budgets, forced-hand buying trigger, slow-moving incumbents. The same explainable demand-and-scheduling engine generalizes to any operation where "why did the system decide this" matters and isn't currently answerable: campus shuttle systems, airport landside operations, hub/circulator routes, and small fixed-route agencies too small to run their own optimization team. We are deliberately not building or pitching that expansion now — it would dilute the actual near-term sell — but the underlying forecasting-plus-audit-trail architecture doesn't change, only the zone/vehicle/policy configuration does, which we've already validated works across different real cities and different transit modalities (paratransit, rideshare-scale demand in two cities, real fare-payment ridership) without touching the core recipe.

---

## Curious

**What convinced you to apply to YC? How did you hear about it?**
`[ARYA/CHRIS: fill in]`

**Anything else we should know?**
`[ARYA/CHRIS: optional — a good use of this slot, if true, is a one-line status update on outreach replies/calls booked, since "traction since we wrote the main answers" is a legitimate thing to add here right before submission]`
