# Milexium: YC deadline execution roadmap

This is the only active backlog through the YC Fall 2026 deadline: **Monday,
27 July 2026 at 8:00pm Pacific Time**, which is **Tuesday, 28 July at 4:00am
British Summer Time**. The internal submission target is **Monday 27 July at
12:00pm PT / 8:00pm BST**, leaving eight hours for failures and form issues.

The goal is not to imitate an enterprise stack in five days. It is to prove one
hard, valuable technical thesis end to end:

> Milexium turns every paratransit scheduling recommendation, denial, and human
> override into reproducible evidence, then replays the outcome to show whether
> the decision improved service, cost, and ADA capacity-constraint indicators.

Chris owns `milexium.com`, Cloudflare, and the marketing site outside this repo.
Arya owns the product/data system, technical evidence, demo backend, and the
technical parts of the YC application. Both founders own customer discovery,
founder answers, videos, and final submission.

## Deadline definition of done

By the internal cutoff, the repository must demonstrate this loop from one
command, using the explicitly fictional reference agency where trip-level public
data does not exist:

```text
import requests -> forecast capacity -> solve schedule -> record decision
-> override one assignment -> verify the ledger -> replay outcomes -> export case
```

The demo is done only if all of these are true:

- A fresh checkout installs from pinned dependencies and passes CI.
- One command seeds a deterministic tenant and runs the complete loop.
- The scheduler enforces pickup/drop-off precedence, time windows, mobility-device
  capacity, shift end, and maximum ride time; it reports solver status and timeout.
- Every recommendation and override records input, policy, model, solver, and code
  versions plus considered alternatives and reason codes.
- A verifier detects any mutation or missing event in the decision chain.
- Replay reports served trips, denials, on-time pickup, excess ride time, deadhead,
  utilization, and changes versus the baseline schedule.
- A redacted JSON/CSV evidence bundle can be generated for one disputed trip.
- Forecast claims remain tied to real aggregate data; dispatch claims remain
  explicitly synthetic until a design partner supplies consented trip-level data.
- The application, product demo, README, and website use the same numbers and do
  not claim customers, production readiness, compliance certification, optimality,
  or incumbent capabilities that have not been verified.

## Product architecture to build

### MilexiumDB: the operational evidence data plane

"MilexiumDB" is a product name for a domain-specific, reproducible data plane on
PostgreSQL, not a new database engine. Building storage primitives from scratch
would add risk without customer value. For the deadline, implement the same schema
in SQLite for a zero-dependency demo, keep SQL portable, and document PostgreSQL
as the production target.

Minimum tables:

| Table | Purpose and invariant |
|---|---|
| `tenants` | Tenant boundary on every operational record. |
| `service_requests` | Immutable request facts and negotiated windows; revisions create new versions. |
| `vehicles` / `drivers` | Capacity, accessibility equipment, shifts, and availability. |
| `policies` | Versioned time-window, ride-time, capacity, and objective configuration. |
| `model_versions` | Training-data manifest, feature schema, evaluation window, and artifact hash. |
| `forecast_vintages` | What was predicted, when, for which horizon, with interval and eventual actual. |
| `schedule_runs` | Solver configuration, status, runtime, objective values, bound/gap, and seed. |
| `decision_events` | Append-only recommendation, rejection, override, and outcome events. |
| `decision_alternatives` | Candidate assignment, feasibility, failed constraints, and objective delta. |
| `outcomes` | Actual pickup/drop-off/service results used by replay and evaluation. |
| `outbox` | Transactional handoff for exports/integrations so state and evidence cannot diverge. |

Every decision event has `event_id`, `tenant_id`, `aggregate_id`, `sequence`, UTC
timestamp, actor type/id, event type, canonical JSON payload, previous hash, and
current SHA-256 hash. The database rejects sequence gaps and duplicate idempotency
keys. Hash chaining is tamper-evident, not legally immutable; say exactly that.
Production design adds PostgreSQL row-level security, encrypted backups, restore
tests, tenant-scoped object paths, and retention policies. Do not add Kubernetes,
Kafka, a graph database, or a custom feature store before measured demand.

### Scheduling and explanation engine

Replace the current greedy demonstration with OR-Tools CP-SAT or routing support.
Use a lexicographic objective: feasibility and policy compliance first, then trips
served, then pickup lateness/excess ride time, then deadhead/cost. Freeze imminent
stops during re-optimization. On timeout, return the best feasible solution plus
bound/gap and use a deterministic safe fallback when no feasible incumbent exists.

Scheduling explanations come from evaluated constraints, never SHAP or generated
prose. Required reason codes: `NO_ACCESSIBLE_CAPACITY`, `PICKUP_WINDOW`,
`DROPOFF_WINDOW`, `MAX_RIDE_TIME`, `SHIFT_END`, `PRECEDENCE`, and `SOLVER_TIMEOUT`.
Forecast explanations may use feature attribution, but must remain visibly separate.

### Replay and evidence API

Expose a narrow interface, initially CLI plus FastAPI if time remains:

- `POST /imports/reference-day`
- `POST /schedule-runs`
- `POST /decisions/{id}/overrides`
- `GET /decisions/{id}/explanation`
- `POST /replays`
- `GET /evidence/{trip_id}`
- `GET /health`, `/ready`, and `/version`

The replay uses identical inputs with a named policy/model/solver version and
produces a signed manifest of metrics and source hashes. It is a comparison tool,
not a causal savings claim. A real savings claim requires shadow-mode operator data.

## Work plan and gates

### Wednesday 22 July: lock scope and repository boundary

Owner: Arya, with Chris confirming the handoff.

- [x] Remove the obsolete tracked website and its duplicated media.
- [x] Make the audit and README treat the website as an external founder-owned system.
- [x] Replace the broad backlog with this deadline plan and sourced competitor map.
- [ ] Create a single `pyproject.toml` or locked requirements file and a CI job for
  compile, unit tests, repository audit, and secret scanning.
- [ ] Add `forge/knowledge/docs/architecture/` with the MilexiumDB entity diagram, event schema,
  threat model, and three ADRs: modular monolith, append-only ledger, SQLite demo /
  PostgreSQL production.

Exit gate: clean audit, clean secret scan, one source of truth for scope, and no
website deployment files in this repository.

### Thursday 23 July: MilexiumDB vertical slice

Owner: Arya.

- [ ] Implement migrations and the minimum tables above.
- [ ] Add a deterministic `Harland County Mobility` seed/reset command using the
  reference-agency generator and a fixed random seed.
- [ ] Implement canonical JSON, event hashing, idempotency, chain verification,
  and tests that prove modification, deletion, reordering, and cross-tenant reads fail.
- [ ] Register the existing AAR model and data manifest without copying model
  binaries or raw rider-level data into Git.
- [ ] Add a machine-readable evidence registry mapping every public metric to its
  script, dataset manifest, split dates, artifact, and limitation.

Exit gate: reset, seed, append, query, and verify run from one command; 100% of
public headline numbers resolve through the evidence registry.

### Friday 24 July: constrained scheduling and decision evidence

Owner: Arya.

- [ ] Implement the OR-Tools constraint model and deterministic fallback.
- [ ] Persist run metadata, assignments, rejected alternatives, constraint reason
  codes, and objective components to MilexiumDB.
- [ ] Add property/invariant tests: no vehicle capacity breach, pickup before
  drop-off, no shift overrun, no duplicate trip service, and deterministic seed replay.
- [ ] Benchmark three fleet sizes and record p50/p95 runtime, feasibility rate,
  objective values, hardware, seed, and timeout. Never claim optimality without proof.
- [ ] Implement a dispatcher override with mandatory actor and reason and show the
  downstream metric delta before it is accepted.

Exit gate: a timed, tested run produces a schedule plus a machine-verifiable answer
to "why this assignment, why not the alternatives, and who changed it?"

### Saturday 25 July: replay, export, and product proof

Owner: Arya. Chris consumes the stable outputs for the site.

- [ ] Build baseline-versus-Milexium replay with served trips, denials, pickup OTP,
  excess ride time, deadhead, utilization, and per-constraint failure counts.
- [ ] Generate a redacted one-trip evidence package and a full-day replay summary.
- [ ] Create a single `demo` command that resets, imports, forecasts, schedules,
  overrides, verifies, replays, and exports in under five minutes.
- [ ] Produce stable screenshots/JSON under `aletheia/artifacts/demo-assets/`; Chris copies
  only final assets and claims into his separately managed site.
- [ ] Draft a 60-90 second product-demo script around the loop, not around model size.

Exit gate: another person can run the demo from README instructions and explain
the value without founder narration.

### Sunday 26 July: credibility, customer, and YC package

Owners: both founders.

- [ ] Run the full clean-room installation on a second machine or CI runner.
- [ ] Complete model/data cards, known limitations, threat model, data handling,
  recovery procedure, and security contact. Use "designed for" rather than
  "compliant" or "certified."
- [ ] Create the shadow-mode design-partner offer: CSV import, no dispatch control,
  30 days, baseline agreed in advance, weekly replay, deletion/return terms, and
  success thresholds for OTP, denials, deadhead, dispatcher time, and evidence time.
- [ ] Conduct five problem interviews or log five concrete attempts with target,
  hypothesis, result, objection, and next step. Do not automate bulk outreach.
- [ ] Replace all founder placeholders, settle CEO/equity/commitment/IP answers,
  and reconcile every metric in the application with the evidence registry.
- [ ] Record founder video and first product-demo take.

Exit gate: application has no placeholders; demo has no unsupported claims; all
technical assertions survive a hostile 20-minute architecture and data-leakage review.

### Monday 27 July: freeze, submit, and preserve evidence

Owners: both founders.

- [ ] By 8:00am PT / 4:00pm BST: code freeze except release blockers; tag the demo
  candidate and rerun CI, audit, chain verification, replay, links, and secret scan.
- [ ] By 10:00am PT / 6:00pm BST: record final founder and product videos; verify
  audio, permissions, captions, URL, mobile rendering, and exact application numbers.
- [ ] By 12:00pm PT / 8:00pm BST: submit the application and save the exact submitted
  text, artifact hashes, commit SHA, video links, and confirmation receipt.
- [ ] Reserve 12:00-8:00pm PT only for correcting submission or infrastructure
  failures. Do not add features after the internal cutoff.

Exit gate: confirmation retained and the exact evaluated product state is reproducible.

## YC scoring lens

| YC signal | Evidence to show by deadline | Failure mode to avoid |
|---|---|---|
| Problem importance | FTA capacity-constraint review surface, $7.06B bottom-up agency opex, operator interview notes | Generic "transport is inefficient" pitch |
| Technical credibility | Real-data backtests, leakage audit, solver invariants, versioned ledger, reproducible evidence registry | Model-size or architecture flexing |
| Product maturity | One-command end-to-end loop, override, replay, export, CI, clean-room run | Screenshots without a working path underneath |
| Go-to-market clarity | Incumbent-adjacent shadow mode, named buyer, 30-day success criteria, deployment/data request | Claiming agencies will replace core dispatch first |
| Defensibility | Normalized decision-to-outcome history, policy semantics, longitudinal replay, implementation learning | Calling public data or a hash chain a moat |
| Overall | Honest boundary between real forecasts and synthetic dispatch proof | Inflated claims, fake traction, or fake compliance |

## Go-to-market wedge

Initial customer: a US small-to-mid-sized ADA paratransit agency or contracted
operator with an existing scheduling system, an operations director who owns OTP
and denials, and a compliance/reporting burden. The first sale is a **shadow-mode
decision evidence layer**, not a rip-and-replace dispatch contract.

Land with a fixed-scope import and replay: ingest booking, schedule, AVL, outcome,
and policy exports; forecast tomorrow's capacity; reconstruct why exceptions arose;
and produce an evidence package. Measure time-to-answer a disputed trip, data
completeness, denial/missed-trip classification, dispatcher override patterns, and
counterfactual operational metrics. Expand only after trust: capacity planning,
then advisory scheduling, then controlled optimization. Price the pilot after
interviews; do not invent a precise price in the application without buyer evidence.

The durable moat is not XGBoost, OR-Tools, public NTD data, or cryptographic hashes.
It is the normalized, permissioned decision-to-outcome corpus across heterogeneous
legacy systems; agency-specific policy encoding; verified replay history; and the
workflow trust earned by making consequential recommendations reviewable.

## Scope kill list until submission

No new foundation model, custom database engine, graph database, Kubernetes,
microservices, Kafka, multi-cloud, driver app, rider app, provider portal, SAML,
SCIM, full SOC 2 program, live PHI, automated dispatch control, broad NEMT pivot,
new large dataset, or unsourced regulation claim. New non-blocking ideas go into a
post-application backlog after submission.
