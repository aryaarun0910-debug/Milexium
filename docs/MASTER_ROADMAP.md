# TransitPulse master roadmap

This is the only active backlog. Completed work belongs in `JOURNAL.md`; obsolete
plans belong in `archive/`. The internal YC submission target is **25 July 2026**.
YC's official Fall 2026 on-time deadline is **27 July 2026 at 8pm PT**.

## Scope rules

- [ ] Finish and validate existing work before adding datasets or architectures.
- [ ] Keep every claim traceable to a public source, script, evaluation window, and limitation.
- [ ] Keep forecasting evidence separate from trip-level scheduling evidence.
- [ ] Keep consequential recommendations advisory until validated with an operator.
- [ ] Put newly discovered non-blocking ideas in `POST_APPLICATION.md`, not here.

## Repository and evidence

- [x] Separate active documentation from dated archives.
- [x] Rename the synthetic pipeline to the fictional `reference_agency/` boundary.
- [x] Separate generated artifacts from source and operating documentation.
- [x] Document tracked, ignored, raw, derived, model, and credential storage tiers.
- [x] Run and pass `py -3 tools/audit_repository.py` after the cleanup.
- [ ] Add a canonical evidence registry mapping every public number to its artifact.
- [ ] Add pinned dependencies and CI for compilation, audits, tests, and secret scanning.

## Data completion and integrity

- [x] Restore missing Chicago checkpoint `2024-12` and rebuild the combined panel.
- [x] Mark current MTA checkpoints as partial and remove unpublished empty Chicago months.
- [x] Finish TLC yellow 2024-2026 and green 2014-present downloads. (334 files, 22GB; audit clean, 0 warnings.)
- [x] Run full FHVHV aggregation. (39.8GB/88 files -> 16.2M zone-hour rows, 1.586B trips. Formal per-file reconcile still open.)
- [x] Add immutable fetch manifests with URL, fetch time, checksum, schema, and coverage. (tools/build_manifests.py -> realdata/manifests/, sha256 per panel.)
- [x] Wire hourly NOAA weather and run an ablation. (weather_ablation.py: hourly adds nothing, all within noise; keep free daily feature, do NOT wire hourly in.)
- [ ] Add formal data contracts (enforced schema + range constraints) for every production panel. (Manifests are a first step, not yet contracts.)

## Modeling rigor

- [x] Model the nationwide NTD monthly panel with temporal and held-out-agency tests. (model_ntd_monthly.py: temporal loses to naive on abs R2 but wins MAPE; cold-start beats naive on 127 unseen agencies. See NTD_MONTHLY_RESULTS.md.)
- [x] Compare Poisson, negative-binomial, Tweedie, and zero-inflated count objectives. (objective_bakeoff.py: Poisson validated for AAR; Gamma best MAPE nationally. True NB/full-ZIP need a custom objective - open.)
- [x] Complete a written point-in-time leakage audit covering every feature and split. (leakage_audit.py: mechanical PASS, 24/24 features. LEAKAGE_AUDIT.md.)
- [x] Run `pretrain_finetune_xgboost.py` and report whether transfer helps low-data targets. (TRANSFER WORKS, controlled: pretrain on Chicago+MTA lifts AAR 0.986->0.991; AAR-only plateaus at 0.986 for any tree count. TRANSFER_RESULTS.md.)
- [ ] Compare transformer quantile calibration with clean split-conformal XGBoost.
- [ ] Add hierarchical reconciliation across agency, zone, day, and hour where supported.
- [x] Create model cards for each published result. (tools/build_model_cards.py -> docs/MODEL_CARDS.md, generated from metrics. Per-source data sheets still open.)

## Newly surfaced (from this session's findings)

- [ ] Switch the NTD monthly production objective to Gamma (best customer-relevant MAPE, 5.2% vs Poisson 12.4%) and headline MAPE; keep Tweedie(1.3) noted as absolute-error-optimal.
- [ ] Combine the two winning axes: pretrained base (transfer) + zone identity, re-run the tree-count control at full pretrain scale on Kaggle (local VRAM capped pretrain at 3M rows).
- [ ] Production weather fix: join the day-ahead weather FORECAST at issue time, not the realized value (leakage-audit caveat; not target leakage but a mild exogenous look-ahead).

## Product proof

- [ ] Turn `reference_agency/` into a named, one-command, resettable fictional tenant.
- [ ] Replace the greedy scheduler with a proven constrained routing solver and deterministic fallback.
- [ ] Create an append-only decision ledger containing data, policy, model, solver, and override versions.
- [ ] Build counterfactual replay with served trips, denials, on-time performance, ride time, deadhead, and utilization.
- [ ] Compute capacity-alert actions from constraints instead of illustrative copy.
- [ ] Build the dispatcher flow: detect risk, schedule, explain, override, replay, and export evidence.
- [ ] Publish the savings calculator with assumptions, provenance, and conservative scenarios.

## Go to market

- [ ] Research and verify the remaining contact worksheet entries.
- [ ] Send additional small personalized outreach batches and log every outcome.
- [ ] Follow up the first SamTrans, Intercity Transit, and Laketran batch around 28 July.
- [ ] Define a shadow-mode design-partner offer, data request, evaluation metrics, and exit criteria.
- [ ] Convert the first substantive reply into a call, data sample, or written pilot next step.

## YC submission

- [ ] Replace every founder placeholder in `docs/yc/application-draft.md`.
- [ ] Resolve CEO, equity split, commitment, relocation, incorporation, and EWB IP answers.
- [ ] Reconcile every metric across the application, website, README, videos, and evidence outputs.
- [ ] Record the one-minute founder video and a separate 60-90 second product demo.
- [ ] Run technical, customer, and YC grill passes with both founders.
- [ ] Verify every URL and save the exact final application text before submitting.
- [ ] Submit on 25 July and retain the confirmation email.

## Explicitly deferred

SAML/SCIM, production PHI handling, SOC 2 audit, driver and rider applications,
provider portals, incumbent-specific integrations, Kubernetes, microservices,
Kafka, multi-cloud, FPGA inference, graph databases, and new foundation-model
work remain out of scope until a design partner creates a measured requirement.
