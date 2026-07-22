# TransitPulse master roadmap: to enterprise-grade, assuming nobody replies

This is the single combined plan. It merges (a) the completion list of everything
outstanding in the repo with (b) the full enterprise R&D document (Product System,
Scheduling Engine, Forecasting & ML, Data & Integration Moat, Enterprise
Architecture, Security & Procurement, Engineering Professionalism). It is
organized around one hard assumption:

**Plan for zero outreach responses.** Batch 1 is out; more will follow. But we
do NOT get to assume a pilot. Every credibility argument that normally leans on
"we have a design partner" must have a substitute that stands on its own. That
substitute is: a demonstrably enterprise-grade product, a compliance-grade
decision-and-replay system, ML rigor nobody can poke holes in, and a fully
deployable fictional reference agency we can demo end to end without a single
real customer. If outreach lands a partner, everything here still applies and
the moat compounds with their data. If it never does, this plan is what makes
TransitPulse fundable and sellable as an idea.

North star (from the R&D doc's "What YC Should See"), our definition of done:
one coherent demo where you **import a day of requests -> detect a capacity
problem -> generate a compliant schedule -> explain a decision -> a dispatcher
overrides it -> export the litigation-ready audit trail**, plus a counterfactual
that replays history and shows what TransitPulse would have done differently.
Everything below serves that demo.

---

## Guardrails (never violate, even chasing "enterprise ASAP")

From the R&D doc's "Do Not Build For Appearances" and our own hard-won lessons:

- **No architecture theater.** No Kubernetes, microservices, Kafka, Spark, feature
  store, multi-cloud, blockchain audit log, custom foundation model, FPGA, or a
  dozen dashboards until a *measured* requirement demands it. A two-founder repo
  with that stack looks *less* credible, not more, because it exposes a mismatch
  between operational scale and architectural complexity.
- **Parameter count is not a selling point.** The transformer already lost to
  XGBoost on real GPUs (0.933 vs 0.986); we ship the trees and say so. Never
  boast size.
- **Every public number traces to a committed, reproducible script.** Real and
  synthetic numbers are never mixed in one claim. EWB's 0.94 R2 is never reused.
- **SHAP explains forecasts, never scheduling decisions.** The scheduling/denial
  trail is deterministic and rule-traceable, always.
- **"SOC2-ready," never "SOC2-compliant"** until actually audited. No fabricated
  compliance.
- **Advisory by default.** Every consequential automation stays advisory until an
  agency explicitly enables it.

---

## Phase 0 - Done (baseline, committed)

Data: AAR paratransit (26.3M bookings), Chicago TNP (548M trips), MTA bus (2.36B)
+ subway (~2B), TLC FHVHV (1.7B, 38GB), TLC yellow taxi 2011-2023, NTD monthly
nationwide (637 agencies, 2.18B trips), NTD annual economics (3,075 agencies),
daily + hourly weather, Census ACS latent-need. Models: AAR 0.986 / Chicago
0.966 / MTA bus 0.949 / MTA subway 0.949, all vs naive; walk-forward backtest;
conformal intervals; SHAP; transformer run (XGBoost won, documented). Product:
synthetic pipeline with deterministic reason codes + audit trail; real demo
assets; savings-calculator backend. GTM: live site, market sizing, design-partner
pitch, 109-target worksheet, batch-1 outreach sent. This is a strong foundation
but it is a *science project*, not yet an *enterprise product*. Phases 1-4 close
that gap.

---

## Phase 1 - Self-sufficient credibility (the no-reply insurance) [HIGHEST PRIORITY]

The point of this phase: make TransitPulse look and behave like real enterprise
software that a diligence reader can inspect, WITHOUT needing a customer. These
are mostly cheap, high-signal, and directly answer "what if nobody replies."

1. **The deployable reference agency.** A realistic fictional agency environment
   that stands up from one command and resets after a demo (R&D: "build a
   realistic fictional agency environment"). This is THE answer to zero replies:
   it lets us run the full end-to-end demo on credible, NTD-anchored synthetic
   operations with zero PHI and zero dependency on a real operator. Extends the
   existing pipeline/ generator into a named, seeded, reproducible "Harland County
   Mobility" tenant.
2. **Compliance-grade decision ledger + replay (the technical centerpiece).**
   Append-only, hash-chained log of every decision: what information was available,
   which policy and model versions were active, what alternatives were feasible,
   why a trip was scheduled or denied, what a dispatcher changed, what happened
   after. At any historical moment we can reconstruct exactly what the system knew
   and recommended (R&D: "compliance-grade replay," "schedule replay"). This is
   more defensible than any forecasting architecture and maps directly to the FTA
   review surface (agencies must track negotiations, denials, missed trips, OTP,
   excessive ride lengths, sometimes across multi-year periods).
3. **Canonical domain model.** Define rider, eligibility, request, trip, stop, run,
   vehicle, driver, provider, policy, decision, audit event (R&D: "define a
   canonical domain model"). Adopt the demand-responsive Transactional Data Spec
   (TCRP Report 210) vocabulary where practical rather than inventing objects.
   Cheap, and instantly reads as "these people know the domain."
4. **Model cards + data sheets + known-limitations page.** Per-model card
   (intended use, limits, evaluation window, provenance), a data sheet per source,
   and a public "where this system should NOT be trusted" page (R&D: model cards,
   NIST AI RMF alignment; "produce a known-limitations page"). Mature teams state
   their limits; this is a credibility multiplier and nearly free given our
   existing honesty-notes culture.
5. **Security posture on paper (not certification).** A written threat model
   (rider-location exposure, malicious exports, cross-tenant access, compromised
   driver device), a security overview, a subprocessor list, privacy notice,
   accessibility statement, a `security.txt` + vulnerability-disclosure address,
   and an enterprise security questionnaire with evidence links (R&D: Security &
   Procurement). "SOC2-ready" posture, documented, no false claims.
6. **Benchmark/evidence-bundle command.** One command that regenerates every
   public claim into a versioned evidence bundle (R&D: "create a benchmark command
   that regenerates every public claim"). Every headline metric gets a provenance
   link, dataset version, evaluation window, limitations note. This makes the
   whole repo audit-proof: anyone can rerun and get our numbers.
7. **Engineering professionalism baseline.** CI gates (format, type, tests,
   security scan), pinned dependencies, ADRs (architecture decision records),
   CODEOWNERS/PR templates, a concise system architecture diagram, a changelog.
   Separate generated data/reports from source; stop committing large generated
   artifacts as if they were application code (R&D: Engineering Professionalism;
   we already gitignore the big panels - formalize this).

## Phase 2 - Unimpeachable modeling (ML depth) [HIGH PRIORITY]

Makes the "these founders can build real ML infrastructure" claim airtight. From
the completion list's section B + the R&D doc's Forecasting & ML.

8. **Model the nationwide NTD monthly panel** (2.18B trips, 637 agencies) - the
   one genuinely novel, unmodeled asset. National paratransit demand nobody has
   modeled: per-agency seasonality, trend, COVID-shock recovery, hierarchical
   structure. Directly powers a bottom-up, defensible market and demand story.
9. **Count-distribution bake-off:** negative-binomial, Tweedie, zero-inflated vs
   Poisson (R&D: "test negative-binomial, Tweedie and zero-inflated"). We have
   never checked Poisson is the right likelihood.
10. **Point-in-time-correct feature audit.** Prove no training feature encodes
    anything not genuinely known at forecast time (R&D: "point-in-time-correct
    feature generation"). A deliberate leakage check, documented.
11. **Hierarchical forecasts reconciled** across agency/service-area/zone/day/hour
    (R&D: "add hierarchical forecasts reconciled across levels").
12. **Forecast vintages + drift monitoring.** Store prediction timestamp, horizon,
    model version, features, intervals, and eventual actual; monitor demand,
    residual, missing-data, and feature-distribution drift (R&D: forecast vintages,
    drift monitoring).
13. **Champion/challenger + shadow inference** before any model swap; measure
    operational value (useful capacity alerts, scheduling-cost delta), not just R2
    (R&D: champion/challenger, "evaluate operational value not just R2").
14. **Uncertainty calibration head-to-head:** the transformer's learned quantiles
    vs XGBoost + split-conformal, by coverage and width across season/zone/demand
    level/weekday/weather (R&D: "report calibration coverage and width by ..."). The
    one place the transformer might still earn its keep - measure before deciding.
15. **Run `pretrain_finetune_xgboost.py`** (built, never run): the warm-start
    transfer test - does pretraining on Chicago+MTA help AAR forecasts.
16. **Bias/equity audit:** are overrides or errors concentrated by geography,
    provider, mobility requirement, or service type (R&D: "measure whether overrides
    or errors are concentrated by ...").

## Phase 3 - The demoable product system [HIGH, gated on Phase 1 domain model]

Build the minimum that makes the North Star demo real. Prioritize ruthlessly:
the dispatcher console + explanation + override + export + the reference agency
ARE the demo. Everything else in the R&D Product System list (driver app, provider
portal, rider notifications, scenario lab, config studio) is a real pilot's
concern - deferred.

17. **Proven scheduling engine to replace greedy v1:** Google OR-Tools VRPTW/
    CP-SAT with pickup-before-dropoff precedence, heterogeneous capacity, wheelchair
    positions, depots, driver shifts/breaks, max ride time; lexicographic objectives
    (compliance/feasibility first, served trips, then lateness/ride time, then
    deadhead/cost); return solver status, runtime, objective, bound, optimality gap;
    deterministic fallback on timeout; rejected alternatives from *actual solver
    constraints* with constraint-level reason codes (we already have the code enum);
    rolling re-optimization with near-term freeze; stochastic/scenario optimization
    under demand + travel-time uncertainty (R&D: entire Scheduling Engine section).
18. **Counterfactual replay harness** against historical/synthetic schedules,
    reporting passenger minutes, excess ride time, OTP, denials, deadhead, fleet
    utilization, cost (R&D: "build a counterfactual replay harness"). This is the
    "one counterfactual result" YC should see, achievable on the reference agency
    with zero real data.
19. **Dispatcher operations console (web):** live vehicle status, unassigned trips,
    late-risk alerts, capacity shortages, route timelines, manual reassignment,
    filtering/search; the "why this trip / why this denial" panel; the manual-
    override workflow (dispatcher changes a decision, writes a reason, sees the
    consequence, creates a permanent audit event); decision comparison
    (recommended vs current vs dispatcher-edited, with cost/served/deadhead/lateness/
    compliance-risk diff). WCAG 2.2 AA, full keyboard, screen-reader semantics
    (R&D: Product System core + Accessibility).
20. **One-click evidence export:** PDF/CSV case file for a complaint, disputed trip,
    audit period, or board report (R&D: "evidence export"). The tangible artifact a
    compliance officer keeps.
21. **Compliance dashboard:** denials, missed trips, late pickups, excessively long
    trips, negotiated times, service-availability trends - the FTA review surface
    (R&D: compliance dashboard; test policy compliance as executable invariants,
    including ADA capacity-constraint indicators).
22. **Savings calculator as a live widget** (backend done): assumptions, sensitivity
    ranges, data provenance shown - not one optimistic number (R&D: "agency savings
    calculator ... show assumptions and provenance"). Public, PHI-free, self-serve
    "wow" that needs no call booked.

## Phase 4 - Enterprise architecture, phased and justified [MEDIUM, real build]

The real foundation the product runs on. Modular monolith first; add heavy infra
only when a measured need appears (guardrails above).

23. **Modular monolith stack:** React/TypeScript, FastAPI/Pydantic, PostgreSQL/
    PostGIS, Redis, OR-Tools, object storage. Deploy containers to a managed
    platform (AWS ECS/Fargate or equivalent), NOT Kubernetes (R&D: Enterprise
    Architecture; explicit "not Kubernetes").
24. **Tenant isolation from day one:** tenant IDs, Postgres row-level security,
    tenant-scoped object paths (R&D). Cheap now, painful to retrofit.
25. **Append-only decision-event ledger with cryptographic hashes** (the Phase-1
    replay system's production home) + transactional outbox so schedules,
    notifications, and audit events cannot diverge (R&D).
26. **MLflow** for experiments/registry/metrics/artifact lineage; **a data lineage
    page** source -> transformation -> feature -> model -> decision -> report (R&D).
27. **Observability:** vendor-neutral OpenTelemetry on API/solver/imports/inference;
    SLOs for ingestion, solver completion, console availability, data freshness;
    structured logs, correlation IDs, health/ready/version endpoints (R&D).
28. **Managed Postgres with PITR, encrypted, tested restores;** migrations, seed
    data, rollback procedures, backward-compatible API changes (R&D).
29. **Data contracts + quarantine** for malformed records; completeness checks,
    duplicate detection, late-arriving-data handling, reconciliation totals;
    immutable raw-source preservation with hashes/timestamps/schemas (R&D: Data &
    Integration Moat - the data-quality half, cheap and high-signal).

### Deferred to a real pilot (named so nothing is "forgotten," not built now)
Driver application, provider portal, rider notifications, scenario laboratory,
configuration studio, standing-order management UI; GTFS Schedule/RT/Flex,
CAD/AVL/telematics ingestion, incumbent-export adapters (TripSpark/Ecolane/
Trapeze), commercial routing matrices/OSRM/Valhalla; Temporal, Dagster/dbt/Pandera,
full SOC2 audit, OIDC/MFA/SAML/SCIM, HIPAA BAAs and PHI-production environment.
Every one of these is real and correct *for a company with a customer and PHI*.
Building them before that customer exists is the appearance-theater the guardrails
forbid. They move to active scope the day a pilot is signed.

---

## Cross-cutting track: outreach + the moat (runs in parallel, always)

Not a phase - a continuous background process, because the one thing that beats
all of the above is a real operator's data.

- Research the remaining 106 worksheet contacts; send in human-paced batches.
- Follow up batch 1 (~28 Jul); track replies; book calls immediately.
- The funnel (design_partner_pitch.md): cold email -> call -> FREE data analysis
  -> design partner -> the compounding decision-outcome moat.
- **If a pilot lands:** their de-identified trip data instantly upgrades every
  claim from "we forecast NYC's public totals" to "we forecast a real operator's
  demand and here's what it saved them," and the deferred pilot-only items above
  activate. This is the only true moat; everything else is credibility.
- **If no pilot lands:** Phases 1-3 still make TransitPulse a fundable, demoable,
  enterprise-grade idea. The reference agency + compliance replay + ML rigor + the
  live calculator are the self-contained proof. We are not dependent on a reply.

---

## Recommended sequencing (what to actually do next, in order)

Given the honest reality that the biggest near-term risk is the **YC application
deadline** (~27 July per YC's Fall 2026 batch; our docs say 25 vs 28 - CONFIRM
THIS FIRST), the sequence is:

1. **CONFIRM the YC deadline and finish the application** (founder work: personal
   answers, equity/CEO, videos, domain, EWB IP check). Nothing below outranks this
   if the deadline is real and days away. The technical foundation is already
   strong enough to apply with.
2. **Phase 1 items 1-2 (reference agency + decision ledger/replay)** - the highest-
   leverage no-reply insurance and the technical centerpiece. Makes the North Star
   demo possible without a customer.
3. **Phase 2 item 8 (model the NTD monthly nationwide panel)** - the one novel
   unmodeled asset, a few hours, strengthens the application's demand/market story.
4. **Phase 1 items 3-7** (domain model, model cards, security posture, benchmark
   command, CI) - cheap, high-signal, done incrementally alongside the above.
5. **Phase 3** (OR-Tools engine -> counterfactual replay -> console -> export) -
   the demoable product, once the domain model and reference agency exist.
6. **Phase 4** as the product needs a real backend to run the demo on.
7. **Phase 2 depth items (9-16)** folded in continuously as modeling rigor.

Outreach runs in parallel through all of it. Revisit and reprioritize this file
every working session; it is the standing plan.
