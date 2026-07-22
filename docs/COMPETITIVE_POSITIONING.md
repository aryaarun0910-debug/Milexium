# Competitive positioning: decision evidence for paratransit

Research checked 22 July 2026. This is a public-material comparison, not a product
teardown. A blank capability means "not established in the cited public material,"
not "the vendor cannot do it." Validate every competitive claim in buyer calls.

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

## Claims discipline

- Say "tamper-evident hash chain," not "immutable blockchain."
- Say "designed to support review," not "litigation-ready" or "guarantees ADA compliance."
- Say "counterfactual replay on a fictional reference agency," not "proven savings."
- Say "validated demand forecasting on real aggregate paratransit data," not
  "validated trip-level scheduling."
- Say "works alongside incumbent systems" until replacement demand is proven.
- Treat absence from a marketing page as unknown, never as proof that a competitor
  lacks a capability.

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
