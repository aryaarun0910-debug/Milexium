# Milexium internal audit

**Date:** 2026-07-26  
**Repository:** `ddd596f243512d8d665f1c9314bef5bb0f3d52d4`  
**Disposition:** direct internal assessment; no code changes or commits made

## Executive verdict

Milexium is not superintelligence, is not Production, and does not yet have a technical moat. It is a unusually disciplined, wide prototype of a high-assurance transport decision system. Its most defensible qualities are the refusal to manufacture certainty, the separation of candidate generators from checkers, the re-derivation of evidence from carried inputs, and a substantial adversarial test culture.

The uncomfortable result is that the central trust claim is weaker than the surrounding engineering:

1. The lifecycle record does **not** prevent backdating. Both its alleged valid-time and transaction-time clocks are caller-supplied.
2. The lifecycle table is **not append-only**. A direct SQL `UPDATE` rewrites history and is read back without any integrity violation.
3. Several active documents use **Validated** or **production model** language despite the repository's explicit rule that no such status is available without consented operator data.
4. The legacy real-data governance checks are partially vacuous. A manifest can point at a nonexistent ignored path or carry a fabricated rights assertion and the targeted tests still pass.
5. The public aggregate research is useful for sector description, but it does not validate dispatch intelligence. Deadhead is not a cost driver in this panel, annual deterioration prediction is effectively null for magnitude, and weather adds almost nothing.
6. The promising new wedge is not “cut deadhead.” It is **restore shared occupancy without worsening denials, lateness, ride time, accessibility, or fairness**. Even that is currently a scoped, biased-subsample hypothesis—not a product result.

The fastest credible path is to stop broadening the platform, repair the trust substrate, obtain one operator's decision-time and outcome data, and build a shadow-mode occupancy/capacity intelligence loop around it.

## What I verified

- Read the repository structure, package surfaces, current status documents, active commercial language, SQL, CI, demo, data manifests, benchmark artifacts, and all 68 ADRs.
- Ran the full local suite: **2,337 passed, 1 skipped, 4 warnings in 755.87 seconds**. The skip is a missing generated GTFS scheduled-deadhead narrative, not an infrastructure failure.
- Ran the main walkthrough from a clean `git archive`: it completed successfully in 2.8 seconds and re-derived 76 quantities with zero mismatches.
- Re-ran `outreach/build_panel_findings.py`: **9 findings survived and 8 were rejected**; the output was substantively unchanged.
- Re-ran all 11 research scripts. Ten reproduced their committed substantive results. `h3_weather.py` did not reproduce byte-for-byte: the rerun lost one agency and changed from 1,994 to 1,886 complete observations. The finding stayed null, but this is a research provenance defect.
- Ran the repository data audit: it passed its own checks over approximately 58 GB of local raw TLC files and the committed/ignored panels.
- Performed controlled adversarial probes and restored every tracked mutation.

Green tests are real evidence of considerable engineering work. They are not evidence that every named guarantee exists.

## Defects — severity ranked

### P0 — the lifecycle “bitemporal” record does not establish transaction time

[`LifecycleTransition`](C:/Users/aryaa/Documents/Milexium/packages/canonical/lifecycle.py:170) accepts both `decided_at` and `recorded_at`; [`record_lifecycle_transition`](C:/Users/aryaa/Documents/Milexium/packages/canonical/storage.py:693) passes both caller values into storage; and the SQL provides no trusted default. Its only database constraint is [`recorded_at >= decided_at`](C:/Users/aryaa/Documents/Milexium/packages/canonical/sql/schema_v0_1.sql:374).

I inserted a transition today whose `decided_at` was `2020-01-01T00:00:00Z` and whose `recorded_at` was one second later. It was accepted. The system proves only that two assertions are ordered. It does not prove when the row entered Milexium or that the decision was recorded contemporaneously.

This makes “refuses backdating” false. It also means `recorded_at` is not transaction time in the usual bitemporal sense.

**Required repair:** the writer/database, not the caller, stamps `recorded_at`; late-arriving decisions are explicit records with measured ingest lag and a declared reason; and the original source timestamp is distinct from Milexium's receipt/commit timestamp. If hostile or evidentiary timestamping matters, anchor signed checkpoint roots outside the database.

### P0 — the lifecycle table is mutable history

The SQL calls the table append-only because application code contains no update/delete path ([schema comment](C:/Users/aryaa/Documents/Milexium/packages/canonical/sql/schema_v0_1.sql:321)). That is a coding convention, not a database invariant.

I wrote a valid denial, issued a direct SQL `UPDATE` changing `actor_id`, committed it, and read the forged actor back through the normal lifecycle API. No violation was reported. The table has no hash chain, immutability trigger, or privilege boundary preventing `UPDATE`/`DELETE`.

This is the highest-severity defect because this record is presented as the answer to “what happened, who decided, and when?”

**Required repair:** the application credential must have `INSERT/SELECT` but no `UPDATE/DELETE`; an owner-separated trigger must reject mutation; corrections must be new events; transitions should be chained or signed; and tests must prove raw SQL update/delete fail under the exact deployment credential. RLS is tenant isolation, not immutability.

### P1 — active claim language violates Milexium's own status contract

The active YC draft says the model is “validated on real ridership data” and “validated on 26.3 million real ... bookings” ([draft](C:/Users/aryaa/Documents/Milexium/docs/yc/application-draft.md:30)). It also says the architecture has already been validated across cities/modalities ([line 101](C:/Users/aryaa/Documents/Milexium/docs/yc/application-draft.md:101)). [`COMPETITIVE_POSITIONING.md`](C:/Users/aryaa/Documents/Milexium/docs/COMPETITIVE_POSITIONING.md:78) instructs the team to say “validated demand forecasting.”

These are direct violations of ADR-0001. Public aggregate data can demonstrate an aggregate forecasting task. It cannot validate operator capacity planning, scheduling, denial explanation, or economic impact.

“Production model recommendation” in the root [`README`](C:/Users/aryaa/Documents/Milexium/README.md:9), “production model” across `realdata/`, and the four “validated as the right objective” labels in [`MODEL_CARDS.md`](C:/Users/aryaa/Documents/Milexium/docs/MODEL_CARDS.md:13) should become:

- “selected in the objective bakeoff” for Poisson/XGBoost;
- “Demonstrated on public aggregate data” for the forecast;
- “local reference artifact,” not production model;
- “no operator validation, pilot, or deployment” wherever the capability could be mistaken for one.

The draft's “every assignment and every denial” language is also too broad. The system can produce exact constraint codes for decisions made through its solver and carry probed alternatives in the demo. It cannot explain every pre-existing operator decision, and the demo correctly leaves the operator's unknown denial reason unknown.

### P1 — the $94M deadhead opportunity is not supported

The YC draft turns a 17.3% annual deadhead accounting share into a $94M opportunity from a hypothetical 10% reduction ([draft](C:/Users/aryaa/Documents/Milexium/docs/yc/application-draft.md:40)). The current research finds virtually no association between deadhead share and cost per trip:

- Pearson with log cost/trip: **+0.017**
- Spearman with cost/trip: **+0.021**
- OLS R²: **0.0003**

That does not mean empty movement has zero operational value. It means the aggregate panel cannot identify avoidability, marginal cost, or savings. The existing teardown code is more honest than the sales draft: it refuses a savings envelope without an operator-supplied fixed/variable cost split.

Delete the aggregate $94M claim. Sell the auditable diagnosis and scenario model, not unmeasured cash.

### P1 — legacy data governance tests permit false records

[`test_realdata_governance.py`](C:/Users/aryaa/Documents/Milexium/conformance/property-tests/test_realdata_governance.py:72) skips existence checks for ignored paths. Its closing assertion accepts the case where all named paths are untracked. I changed the Chicago manifest from a real local directory to a definitely nonexistent ignored directory; the targeted test still passed.

The rights test requires only more than 40 characters, no short placeholder word, and the word “commercial” ([lines 43–50](C:/Users/aryaa/Documents/Milexium/conformance/property-tests/test_realdata_governance.py:43)). I replaced the Chicago rights field with:

> Fabricated audit assertion: commercial use is permitted because this sentence says so, without any source or legal terms.

The test passed.

These five legacy manifests also have `source_checksum: null` and empty `quality_tests`. Several say bytes are “retained as committed evidence” even though the large directories are ignored. These are unverified declarations, not governed acquisitions.

**Required repair:** every retained dataset needs an exact source URL, captured terms/license URL and hash, acquisition timestamp, byte/object hash, size, schema fingerprint, required quality checks, local presence status, and an explicit `legacy_unverified` state until backfilled. A clean checkout should never claim locally absent bytes are retained.

### P1 — lifecycle and evidence guarantees are split in a misleading way

The decision-event ledger is hash-chained and re-verifiable. The newer lifecycle record is not. The walkthrough can truthfully say its three decision events are hash-chained; that should not bleed into the implication that the request lifecycle history has the same property.

The standalone evidence verifier is a strong reproducibility artifact, but [`pack_file.py`](C:/Users/aryaa/Documents/Milexium/packages/evidence/pack_file.py:95) correctly admits what it does not attest. An embedded verifier cannot authenticate itself: an attacker who replaces the pack, claims, and embedded verifier together can create a self-consistent forgery. This needs an external verifier hash/signature, a separately distributed implementation, and anchored signed roots before “independent” is allowed to imply authenticity rather than self-contained recomputation.

### P1 — the canonical model still cannot drive its own teardown

The current walkthrough states the gap plainly: neither the intake contract nor `Outcome` carries trip end time, so it reads the unmapped `ActualDO` column directly ([walkthrough](C:/Users/aryaa/Documents/Milexium/demo/walkthrough.py:873)). The canonical records therefore cannot drive one of Milexium's flagship analyses.

Add observed dropoff/end time with provenance and missingness semantics to the canonical outcome/operational record. Then prove export → canonical store → teardown without reaching back into raw vendor columns.

### P2 — research is not fully reproducible

`h3_weather.py` fetches/reuses a live external weather source without a fully pinned observation set. The committed artifact has 1,994 observations and 20 agencies; the 2026-07-26 rerun produced 1,886 and 19. The result remained null, but the sample changed.

Research artifacts need immutable input snapshots or content hashes, source retrieval timestamps, exact join/exclusion counts, environment lock, and a generated-artifact drift check. A result that remains directionally similar is not the same as a reproducible result.

### P2 — the clean CI signal is narrower than the status language

The main Python CI installs formal and solver extras, then runs `python -m pytest packages/ conformance/ -q` ([workflow](C:/Users/aryaa/Documents/Milexium/.github/workflows/ci.yml:41)). It does not provision Postgres/PostGIS/MinIO, so service-backed tests are designed to skip in a clean runner. It also does not run the demo, research reproduction, repository data audit, Python lint/type checking, dependency audit, migration upgrade paths, or mutation tests.

The local 2,337-pass result is meaningful, but it was obtained on the founder's provisioned machine with ignored model/data artifacts and live databases. “CI green” does not mean the multi-service deployment was exercised.

Create two explicit lanes:

1. **Hermetic unit/contract lane:** no unexpected skips; clean archive; demo smoke; generated contract drift; standalone verifier.
2. **Provisioned integration lane:** Postgres/PostGIS/MinIO service containers, exact non-superuser credentials, migration upgrade tests, RLS/immutability probes, and zero skipped tests in the selected integration set.

Add Ruff, Pyright or mypy, dependency and secret scanning, SBOM generation, `cargo audit`, npm audit policy, and a scheduled mutation lane. Test counts should stop being used as a proxy for assurance.

## Vacuous tests — controlled mutations

I ran two mutations against the Chicago legacy governance manifest. Neither should be able to pass a test advertised as proving that the manifest points at real bytes and declares real rights.

| Mutation | Targeted test | Result |
|---|---|---|
| Replaced `already_present_at: realdata/panels/chicago_monthly/` with `realdata/panels/definitely-not-present-audit-mutation/` | `test_each_manifest_points_at_paths_that_actually_exist` | **Passed**: 1 passed, 15 deselected |
| Replaced the rights field with an explicitly fabricated sentence that merely contained “commercial” and exceeded 40 characters | `test_each_manifest_loads_and_declares_real_rights` | **Passed**: 1 passed, 15 deselected |

Both mutations were restored exactly. The reason is structural, not incidental: ignored paths are skipped and the closing assertion accepts a manifest for which every path is untracked; rights are checked as prose shape, not against a captured legal source.

The lifecycle probes were adversarial state mutations rather than test-code mutations:

- A transition asserted to have been decided and recorded in 2020 was inserted in 2026 and accepted.
- A direct SQL update changed the recorded actor and the normal read API accepted the forged value.

Those probes verify the P0 defects independently of whether any existing test passes.

## Stale — documentation that cannot be trusted as current

- [`docs/HANDOFF.md`](C:/Users/aryaa/Documents/Milexium/docs/HANDOFF.md:7) says the six priorities were killed/incomplete, cites old HEADs, and lists completed work as in flight. Its header tells readers to use it first. Archive it or replace it with a generated current handoff.
- [`IMPLEMENTATION_STATUS.md`](C:/Users/aryaa/Documents/Milexium/IMPLEMENTATION_STATUS.md:441) still lists closed items as open, including teardown latency, generated TypeScript drift, ModelRegistry persistence, and container RLS. It is designated as the living source of truth and currently is not one.
- [`README.md`](C:/Users/aryaa/Documents/Milexium/README.md:43) calls `data/` a “Governed 250 GB estate.” The local audit found roughly 58 GB of large raw TLC data plus panels, much of it outside the governed acquisition path. The 250 GB figure is a design target, not current governed volume.
- [`packages/README.md`](C:/Users/aryaa/Documents/Milexium/packages/README.md:19), [`research/README.md`](C:/Users/aryaa/Documents/Milexium/research/README.md:22), and [`benchmarks/README.md`](C:/Users/aryaa/Documents/Milexium/benchmarks/README.md:19) materially understate or misdescribe what now exists.
- [`docs/MASTER_ROADMAP.md`](C:/Users/aryaa/Documents/Milexium/docs/MASTER_ROADMAP.md) is still presented as active/canonical while carrying completed CP-SAT and other work as unchecked backlog.
- Historical ADRs are generally admirably explicit about limitations and later corrections. The principal ADR problem is not hidden contradiction; it is that active summaries failed to absorb the later ADRs.

The fix is not another narrative sweep. Generate capability/status tables from a small machine-readable registry, require each status claim to name its evidence and limitation, and expire handoff documents automatically.

## Suppressed research — rerun verdicts

| Script / hypothesis | Result | Disposition |
|---|---:|---|
| H1 scheduled vs operated DR deadhead | GTFS side is fixed-route; only 9 name matches; implied 1–69 service days | **Killed.** The sources do not describe the same service. |
| H2 next-year cost deterioration | 2024 R² vs zero only 0.007–0.026; AUC about 0.59–0.61 | **Magnitude prediction killed.** Weak risk ranking is exploratory, not a product. |
| H2b ablation | Structural-only features do not recover useful magnitude accuracy | **Killed for public annual data.** More model complexity is not the answer. |
| H3 weather anomalies | R² about 0.0014; unstable signs across agencies | **Killed.** Also not byte-reproducible on rerun. |
| H3b snow-season mechanism | Snow metros had no deeper winter trough than warm metros | **Killed.** Seasonality exists (median amplitude 16.7%), but this weather story does not. |
| H4 disability population as unmet need | Disability population R² 0.449; total population R² 0.526; 13.5× service-intensity spread | **Exploratory descriptive signal, not unmet need.** Confounded by eligibility, alternatives, reporting, and multi-operator mapping. |
| H5a reporting discontinuities | 2.6% transitions flagged; real cost trend survives removal | **Useful QA.** Flags are not proven reporting errors, but the +34% real cost/trip trend is robust. |
| H5b deadhead/contracting/scale explain cost | Deadhead R² 0.0003; within-agency contracting correlations near zero; scale Spearman +0.059 | **Killed as general explanations.** Contracting subgroups are small enough for a future causal event study, not a current claim. |
| H5c cost decomposition | Real cost/trip +34%; 61.6% cost/hour, 38.4% productivity | **Strong public-data description.** Not an intervention estimate. |
| H5d productivity anatomy | Trips/hour −10.6%; vehicle miles/trip +11.5%; speed −0.3%; 97.1% of log decline is miles/trip | **Strong description.** It narrows the mechanism but does not distinguish geography from pooling by itself. |
| H5e ride-sharing/occupancy | In 355 full reporters, occupancy −10.0%; median agency −9.4%; 66.8% fell | **Promising scoped hypothesis.** Only 26% of balanced agencies, biased toward larger/costlier operators, though covering 66.3% of trips. |

The panel-findings gate's nine survivors remain useful descriptive outreach facts. The eight rejections should stay rejected, with two narrow exceptions worth separately pre-registering:

- Fleet utilization changed −3.9% in aggregate and −5.5% at the median agency. It missed an arbitrary 5% effect floor. This may be operationally meaningful, but changing the threshold after seeing the result would be p-hacking by another name. Pre-specify a decision-relevant floor and retest on a future vintage.
- The original “pooling efficiency declined” finding used passenger trip length and weak coverage. H5e identifies the correct construct—passenger miles per vehicle revenue mile—and supports a **large/full-reporter** occupancy decline. It does not rescue a sector-wide statement.

One other rejection can be scoped but not rescued as written: DR real cost growth exceeded bus by 10.6 percentage points in the weighted aggregate but only 3.7 points at the median agency. That is a large-operator-weighted description, not a typical-sector effect. The extreme-deadhead tail is only 9 of 406 full reporters and concentrated among tiny operators; it is a case-finding list, not a sector finding. Cost-dispersion widening (−1.1%), deadhead→cost, the volatility story, and the mechanically coupled recovery→productivity claim are substantive nulls/rejections, not casualties of the gate.

The genuinely underpowered branch is contracting/intervention change: only 18 agencies increased taxi/TNC share by more than 25 points, 47 decreased it, and 81 substantially increased purchased transportation. A matched event study with several pre/post years, contract dates, service mix, wage environment, urbanicity, and operator fixed effects could settle a narrower causal question. H2 is not underpowered in row count—its 2024 holdout has 1,804 agencies—but annual aggregates lack the leading operational variables the task needs. H4 is confounded rather than simply underpowered. H5e has enough observations for its scoped description; its problem is selection bias.

Dead for now: weather, the volatility myth, aggregate deadhead as a cost predictor, cost-dispersion widening, and mechanical “recovery drives productivity.”

## Strategic — model and forecasting

### Is vehicle-hour cost asymmetry worth keeping?

Keep the asymmetric-loss **interface**, but demote the current +7.3% empirical improvement from strategic evidence. It is good product design to let an operator state that under-provisioning and over-provisioning have different costs. The current backtest cannot make that mechanism decisive because realized NTD vehicle-hours and trips are monthly served quantities, latent unmet demand and denial harm are absent, and the cost weights are illustrative rather than estimated from an operator.

The mechanism earns headline status only if:

1. under- and over-provision costs are elicited or estimated from an operator's staffing, subcontracting, denial, overtime, and unused-capacity outcomes;
2. forecasts are evaluated on daily/run-level decisions, not only monthly aggregates;
3. decision regret is reported across a pre-specified cost-weight range with uncertainty;
4. the asymmetric policy beats the same point forecast under symmetric and incumbent rules on a prospective holdout;
5. service and accessibility non-inferiority constraints are met.

Until then, the point forecast is the result and the asymmetry is a configurable policy layer.

## Strategic — frontier assets and what is actually defensible

### 1. Failure-aware evidence semantics

Milexium frequently says “unknown,” distinguishes observed from modelled, refuses guaranteed savings, carries unattributable segments, and withdraws interval coverage under drift. This is culturally and technically valuable. It is rebuildable, but most competitors do not assemble it coherently.

### 2. Generator/checker separation

The DARP feasibility checker, evidence re-derivation, Python/Rust verifier parity, contract drift gates, RLS negative controls, and mutation-minded tests are the best parts of the repository. The CP-SAT relaxation bound appears mathematically coherent and the externally checked solutions are legitimate.

The limitation is scale: three small benchmark instances are credibility evidence, not a state-of-the-art solver evaluation. A competent OR engineer could reproduce the current solver/benchmark position in roughly 2–4 weeks.

### 3. Operator intake discipline

The PII-first quarantine, non-retention of unknown extension values, semantic-loss records, and explicit distinction between the operator's reason and Milexium's counterfactual reason form a strong design-partner intake posture.

### 4. Adversarial tenant-isolation work

The RLS work contains real negative controls and caught several classic false greens: owner/superuser bypass, empty-string GUC behavior, and a tamper test that would have updated zero rows. This is more serious than typical prototype security work, although it remains dev infrastructure rather than a deployed security program.

### What is not a moat

- Current lifecycle “bitemporality”: days to reproduce, and currently defective.
- Z3 invariants: useful discipline, but the proofs cover a hand-transcribed eight-state graph and a conditional injective hash function. A strong engineer can reproduce them in days.
- Standalone verifier: one to two weeks to reproduce; authenticity still needs an external trust anchor.
- Public-data forecasts: conventional XGBoost with strong autocorrelated lag features. Useful baseline, not proprietary intelligence.
- Breadth of packages/ADRs: impressive output, but breadth without deployments creates maintenance cost rather than defensibility.

The current integrated prototype could be recreated by a capable small team in roughly 2–3 months. The hard-to-rebuild asset would be a longitudinal, rights-clean corpus of operator decision-time states, actions, alternatives, overrides, and outcomes—plus evidence that Milexium improves them safely. That asset does not exist yet.

## The intelligence layer Milexium should become

Do not make an LLM the brain. Use an LLM only for schema-mapping assistance, investigator queries, and translating verified structured reasons into audience-specific prose. The authoritative intelligence should be a probabilistic world model plus a constrained planner and independent verifier.

### Objective

Optimize **feasible shared occupancy and protected capacity**, subject to:

- no increase in denials or missed trips;
- pickup and ride-time constraints;
- wheelchair/accessibility capacity;
- driver and vehicle rules;
- explicit negotiated-window policy;
- fairness constraints and stratified service guarantees;
- operator-chosen risk/cost tradeoffs.

Deadhead becomes one measured consequence, not the master objective.

### Architecture

1. **Temporal event substrate.** Immutable receipt-time events for requests, negotiations, schedule snapshots, assignments, overrides, vehicle state, pickups/dropoffs, cancellations, no-shows, denials, and policy versions. Preserve what was known at each decision instant.
2. **Operator world model.** Travel-time distributions, dwell, show-up/no-show, cancellation hazard, vehicle/driver/equipment state, service eligibility, and future demand distributions. Keep epistemic uncertainty explicit.
3. **Compatibility hypergraph.** A request is a node. An edge or hyperedge exists when requests can share a vehicle while satisfying windows, capacity, ride time, accessibility, and fairness. Predict the probability and marginal value of each feasible pooling opportunity.
4. **Stochastic rolling-horizon planner.** Use exact CP-SAT/MILP as an offline teacher and bound source; deploy a faster heuristic/policy online; re-optimize on booking/cancellation/vehicle events; independently verify every emitted plan.
5. **Capacity opportunity model.** Estimate the future accessible slots consumed or preserved by a present assignment. Output structured claims such as: “Assigning this booking here preserves an estimated 2.1 wheelchair-compatible slots over the next 90 minutes, with this uncertainty and these binding constraints.”
6. **Counterfactual evaluator.** Compare incumbent and Milexium in shadow mode on the identical information set. Measure regret against a clairvoyant offline bound, not only against a weak greedy baseline.
7. **Evidence and safety layer.** Signed receipt timestamps, immutable correction events, solver/checker separation, policy-version hashes, stratified constraint audits, and a portable externally anchored evidence pack.

The frontier move is not a transformer. It is learning the **opportunity cost of an assignment under future uncertain demand while producing a feasible, inspectable plan**.

### Data contract for the first operator

Ask for 8–12 weeks, not a heroic historical dump:

- pseudonymous request/trip id and optional stable pseudonymous rider id;
- request receipt time and every negotiation/update time;
- requested and accepted pickup/dropoff windows;
- coarse or appropriately protected origin/destination;
- mobility equipment, companions, assistance and vehicle constraints;
- schedule snapshots at each decision/re-optimization point;
- assigned vehicle/run/driver pseudonyms and shift/equipment state;
- candidate/rejected alternatives if the incumbent exposes them;
- dispatch overrides and reason;
- actual arrival, pickup, dropoff and completion times;
- cancellation/no-show/denial/missed-trip state and recorded reason;
- AVL/MDT positions at roughly 5–30 second resolution, with revenue/non-revenue state when available;
- policy version, service area, holiday, planned disruptions, and source-system clock metadata;
- operator cost components only if economic claims are desired.

No direct names, phones, addresses, medical narratives, or free-text notes. Tokenization should occur at the operator. The agreement must define purpose, access, retention, deletion, incident handling, publication rights, and whether derived aggregates/models may be retained.

TIDES is useful as an operational interchange target because it covers vehicle locations, passenger counts, and fare transactions ([official TIDES documentation](https://tides-transit.org/main/)). GTFS Flex is useful for discoverability, zones, and booking rules, but it describes flexible service availability—not performed paratransit decisions ([official GTFS Flex documentation](https://gtfs.org/community/extensions/flex/)). Cal-ITP's public speed maps can supply fixed-route travel-time priors and tooling evidence, but they are derived from archived GTFS-Realtime vehicle positions and should not be called DR ground truth ([California Transit Speed Maps](https://analysis.dds.dot.ca.gov/rt/)).

### Public-data acquisition, in order

1. Pin and fully govern what is already used: NTD, AAR, Chicago, MTA, NOAA/Open-Meteo, TLC, and Cal-ITP. Backfill exact licenses, byte hashes, and immutable snapshots.
2. Acquire more years and fields from NTD for robust sector descriptions, not dispatch validation.
3. Acquire rights-clean GTFS Flex/GOFS examples for integration coverage. GTFS Flex became part of the official specification in 2024, but its role is service discovery and booking rules, not individual operational outcomes ([GTFS feature overview](https://gtfs.org/getting-started/features/overview/)).
4. Use Cal-ITP/other open GTFS-RT archives for fixed-route movement priors and ingestion stress tests only.
5. Add ACS/LODES/service-area covariates for cold-start priors, with explicit ecological limitations.
6. Pursue public-records requests or research agreements for anonymized AVL/dispatch extracts where legally appropriate. Do not pretend public GTFS can substitute for operator DR records.

This can remain local and free: MinIO, Parquet/DuckDB, PostgreSQL/PostGIS, and encrypted backups. Paid cloud is not the bottleneck.

## Build order

### Next 14 days — make the claims true

1. Fix lifecycle receipt time and database immutability; add raw-SQL adversarial tests.
2. Remove every active “Validated,” “production model,” $94M, and “every decision” overclaim.
3. Add canonical trip end/dropoff and prove intake → store → teardown.
4. Replace legacy manifest assertions with evidence-bearing governance and explicit `legacy_unverified`.
5. Split hermetic CI from provisioned integration CI and fail on unexpected skips.
6. Freeze/pin research inputs; make every generated research artifact reproducible.
7. Archive stale handoffs and generate status from one capability registry.

Do not add another package, language, formalism, or broad dataset during this period.

### Days 15–45 — build the operator shadow loop

1. Finalize the minimum data agreement and secure transfer path.
2. Implement decision-time schedule snapshots and the compatibility hypergraph.
3. Establish incumbent replay with strict information cutoffs.
4. Define safety metrics and stratification before tuning:
   - feasibility violation rate: exactly zero;
   - denial/missed-trip change;
   - pickup lateness and excess ride time;
   - occupancy and vehicle-miles/trip;
   - wheelchair-compatible capacity preserved;
   - calibration/coverage and failure abstention;
   - latency and planner optimality/bound gap.
5. Run entirely in shadow mode. No dispatcher-facing recommendation until replay integrity is proven.

### Days 46–90 — earn the word Validated

1. Conduct a prospective shadow evaluation on consented operator data against the declared incumbent baseline.
2. Pre-register the primary metric and non-inferiority safety constraints.
3. If shadow results pass, run a carefully staged human-approved pilot.
4. Publish one narrow claim, such as:

> On operator X's consented holdout period, Milexium increased passenger-miles per vehicle-mile by Y% while remaining non-inferior on denials, on-time pickups, excess ride time, and accessibility-stratified service, under the operator's declared policies.

Only then is **Validated** available for that exact task, population, baseline, and period. It does not promote the whole platform.

## Final strategic judgment

Milexium's best instinct is not the number of models, packages, tests, ADRs, or languages. It is the insistence that a system should know when it does not know and carry the evidence for what it did.

Its present risk is mistaking extensive scaffolding for accumulated intelligence. The repository has become broad faster than its core claims have become true. The right move is contraction:

- repair the trust record;
- constrain language to evidence;
- stop treating deadhead as the universal wedge;
- make occupancy/capacity the testable intelligence hypothesis;
- obtain operator decision-time data;
- prove improvement in shadow mode with safety constraints.

If Milexium does that, the eventual moat is not “AI for paratransit.” It is an operator-specific, continuously learning, evidence-bearing decision system that can improve shared capacity while proving it did not sacrifice the riders most exposed to failure.

That would be hard to rebuild. The current repository is the disciplined beginning of it, not yet the thing itself.
