# Competitive positioning: decision evidence for paratransit

Research checked 22 July 2026; status contract added 26 July 2026. This is a
public-material comparison, not a product teardown. A blank capability means
"not established in the cited public material," not "the vendor cannot do it."
Check every competitive claim in buyer calls.

**Before writing any outward-facing copy, read "The status contract" below.**

## Market reality

The category is not empty and incumbents are not merely old black boxes. Public
materials show mature scheduling, dispatch, rider, reporting, and real-time
optimization products:

| Vendor | What its own public material emphasizes | Implication for Milexium |
|---|---|---|
| Ecolane | Real-time trip-level optimization, scheduling/dispatch, rider access, reporting, and ADA/NEMT support; 300+ agencies and 16,000+ vehicles claimed. [Source](https://www.ecolane.com/) | Do not compete on "dynamic scheduling exists." |
| TripSpark / NovusDR | Booking, client/funding records, automated scheduling, real-time dashboard, dispatch changes, driver updates, and reporting; 450+ agencies claimed. [Source](https://www.tripspark.com/paratransit-demand-response-software/scheduling-and-dispatching/) | Do not pitch generic workflow digitization or drag-and-drop dispatch. |
| Trapeze PASS | A broad paratransit suite spanning bookings, dispatch, scheduling, integrations, and reporting; current product documentation describes PASS and cloud-based OneMobility. [Source](https://collaborate2.trapezegroup.com/tag/dr/) | Assume deep installed workflow and integration costs. Enter alongside it. |
| Spare | A unified, AI-native transit platform across paratransit, microtransit, fixed route, fleet, compliance, and reporting. [Source](https://spare.com/) | "Modern AI interface" is not differentiation. |
| RideCo | Continuous optimization that re-evaluates traffic, capacity, breaks, locations, and trips every 20 seconds, plus rider channels. [Source](https://rideco.com/paratransit/scheduling) | Do not claim faster re-optimization as the wedge without measured proof. |
| Via / Routematch | Uber acquired Routematch after it had served 500+ agency partners; the combined positioning covered paratransit, payments, fixed-route tools, and planning. [Source](https://www.uber.com/en-HN/newsroom/uber-routematch/) | Platforms have distribution and multimodal breadth Milexium cannot match yet. |

## The narrow opening

Public vendor pages consistently lead with efficient scheduling, dispatch,
real-time operations, rider experience, and general reporting. FTA reviews,
meanwhile, inspect the lineage behind specific operational outcomes: negotiated
and requested times, actual arrivals, denials, missed trips, lengthy trips,
complaints, carriers, and corrective actions. The governing rule treats recurring
untimely pickups, missed/denied trips, and excessive trip lengths as possible
capacity constraints. [49 CFR Part 37](https://www.transit.dot.gov/regulations-and-guidance/civil-rights-ada/part-37-transportation-services-individuals-disabilities)
An FTA review request illustrates the concrete records agencies may need to
assemble. [FTA review report](https://www.transit.dot.gov/sites/fta.dot.gov/files/docs/Met_Council_Paratransit_Final_Report.pdf)

The defensible hypothesis is therefore narrower than "incumbents cannot explain
decisions":

> Agencies need a vendor-neutral evidence layer that reconstructs what data,
> policy, model, solver, feasible alternatives, and human overrides produced an
> operational outcome, then links that decision to what actually happened.

This must be tested in customer interviews. It is currently a product thesis,
not a proven market fact.

## Positioning

**Category:** decision evidence and replay for demand-response transportation.

**One sentence:** Milexium sits alongside existing paratransit dispatch software
and turns forecasts, scheduling recommendations, denials, and overrides into
reproducible evidence tied to operational outcomes.

**Buyer:** operations director first; compliance/ADA coordinator and scheduling
manager as co-users; IT/security and procurement as gates.

**Land motion:** 30-day shadow-mode import and replay with no control of live
dispatch. The agency keeps its incumbent. Milexium ingests exports, identifies
data gaps, recreates exception evidence, and produces agreed operational metrics.

**Expansion:** capacity forecasts -> exception triage -> advisory schedule
comparison -> controlled optimization after the agency validates policy encoding.

## Capability wedge to prove

| Capability | Deadline proof | Why it matters |
|---|---|---|
| Decision lineage | Version and hash every input, policy, model, solver run, alternative, and override | Makes a decision reproducible rather than merely logged |
| Constraint-native explanation | Persist exact failed constraints and objective deltas | Explains scheduling mechanics without generated prose |
| Temporal replay | Re-run with only information available at the historical decision time | Prevents hindsight leakage and supports credible comparison |
| Outcome closure | Join recommendations and overrides to pickup, drop-off, denial, ride-time, and cost outcomes | Creates the learning loop and eventual data moat |
| Vendor-neutral import | Stable canonical schema plus provenance and reject reports | Enables an incumbent-adjacent land motion |
| Evidence export | Redacted case file and period summary with manifest and hashes | Turns technical lineage into a buyer-visible artifact |

## The status contract — read this before writing any outward-facing copy

This repository has exactly one status vocabulary, fixed by ADR-0001, and it
governs every document, deck, email, application, README, and docstring:

> **Exists → Specified → Demonstrated → Validated → Production**

**Validated requires consented operator data against a declared baseline.
Milexium has none — zero customers, zero pilots, zero operator data. Therefore
nothing Milexium does is Validated, and no sentence we publish may say it is.**

Public aggregate data (NTD, TLC, MTA, Chicago, GTFS) can **demonstrate** an
aggregate forecasting task. It can never **validate** operator capacity planning,
scheduling, denial explanation, or economic impact. The ceiling is set by the
data, not by how well the code works or how many tests pass.

Three rules that follow, and that keep getting relearned the expensive way:

1. **Never write "validated," "proven," "guaranteed," or "production model"**
   about a Milexium capability. The honest words are *demonstrated*, *measured*,
   *reproduced*, *re-derived*, *reference implementation*. They are also the
   words that survive contact with a domain expert, which the other set does not.
2. **Never publish a savings, ROI, or "opportunity" figure.** We have no operator
   cost split, so we cannot separate avoidable cost from fixed cost. The
   teardown code already refuses to emit a savings envelope without one; copy
   does not get a lower standard than code. An arithmetic percentage of a real
   total is still an invented claim if nothing establishes the lever works —
   this is exactly how the $94M deadhead figure got written, and it was deleted
   on 2026-07-26 once the association it assumed was measured: Pearson +0.017
   against log cost per trip and OLS R² 0.0003 over 405 operators
   (`research/h5b_structure_vs_cost.json`). The findings gate had already
   rejected the same claim independently at Spearman +0.024 over 406 operators
   (ADR-0058, `outreach/panel_findings.json`).
3. **Every number must name its artifact.** `outreach/panel_findings.json` (gate
   passed), `research/*.json`, a benchmark artifact under `benchmarks/`, an ADR,
   or `realdata/metrics_real.json`. If a claim cannot name one, delete it — do
   not soften it into something vaguer and unfalsifiable.

Earning **Validated** takes a prospective shadow evaluation on one operator's
consented data against their declared incumbent baseline, with the metric
pre-registered. When that happens it promotes exactly that task, population,
baseline, and period — never the platform.

## Claims discipline

- Say "tamper-evident hash chain," not "immutable blockchain."
- Say "designed to support review," not "litigation-ready" or "guarantees ADA compliance."
- Say "counterfactual replay on a fictional reference agency," not "proven savings."
- Say "demand forecasting demonstrated on real aggregate public data, with no
  operator pilot," not "validated demand forecasting" and never "validated
  trip-level scheduling." The forecast is aggregate; dispatch is not validated at
  any grain.
- Say "selected in the objective bakeoff" for a modelling choice, not "validated
  as the right objective."
- Say "reference implementation" or "the model we ship," not "production model."
- Say "works alongside incumbent systems" until replacement demand is proven.
- Treat absence from a marketing page as unknown, never as proof that a competitor
  lacks a capability.
- Where an operator made the decision, say the reason is **unknown**. We can
  produce an exact constraint code for a decision our own solver made and carry
  the alternatives it probed; we cannot explain a pre-existing operator decision,
  and back-filling a plausible reason would be the worst thing this product
  could do.

## Interview questions that can falsify the wedge

1. Walk me through the last disputed denial or missed trip. Which systems and
   people were needed, and how long did the answer take?
2. Can you reconstruct the requested time, negotiated time, schedule version,
   vehicle constraints, dispatcher edits, and final outcome from one record?
3. Which reports are routine, and which evidence still requires spreadsheets or
   manual log review?
4. Would a read-only shadow layer pass your data/security gate? Which export from
   your current vendor is actually available and at what cadence?
5. What measurable result would justify a paid pilot: fewer misclassified denials,
   faster complaint response, better OTP, lower deadhead, or less dispatcher time?
6. If your incumbent added this next quarter, what would make a separate Milexium
   product unnecessary? The answer defines or invalidates the moat.
