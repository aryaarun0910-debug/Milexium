# Open-core business and defensibility

## Why open anything

The open component should remove adoption friction, establish contracts, invite
external validation, and make benchmark results reproducible. It should not expose
customer data, proprietary deployment operations, or every commercial capability.

Open source is a distribution and trust strategy, not a substitute for users.

## Recommended boundary

### Open: Milexium community components

- canonical schemas and validators;
- reference CSV and GTFS/GTFS Flex adapters;
- local fictional reference agency;
- task/model/solver/policy plugin interfaces;
- baseline forecasts and simple reference solver;
- evidence format and verifier;
- local replay/evaluation runner;
- benchmark definitions, metrics, and public dataset preparation;
- Python SDK/CLI;
- conformance fixtures;
- documentation and examples.

### Commercial: Milexium Cloud

- managed ingestion and connector operations;
- hosted model/solver execution;
- tenant collaboration and approvals;
- model/policy/solver registries with managed promotion;
- monitoring, alerts, lineage UI, and long retention;
- scalable replay and benchmark execution;
- managed security, backups, high availability, and support;
- private adapter/model/solver hosting;
- enterprise evidence exports and review workflows.

### Enterprise

- private cloud/on-premises deployment;
- custom and incumbent connectors;
- identity/provisioning integration;
- data residency and private networking;
- contractual SLOs and support;
- custom policy implementation;
- dedicated training/evaluation;
- security/procurement evidence and customer-managed keys where justified;
- white-label or embedded API rights.

## Licensing decision

Candidate recommendation for legal review:

- Apache License 2.0 for schemas, SDK, plugin interfaces, verifier, examples, and
  baseline community runtime.
- Commercial license for hosted control-plane services, proprietary connectors,
  managed operational tooling, and enterprise packages.
- Trademark policy for the Milexium name and conformance marks.
- Developer Certificate of Origin or contributor agreement before accepting
  material external contributions.

Apache 2.0 is OSI-approved and includes an explicit patent-license section. The
choice still requires founder and counsel review; this blueprint is not legal
advice. [OSI license list](https://opensource.org/licenses) ·
[Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0.html)

Do not call a source-available restriction "open source." If future server-side
code uses a non-OSI license, label it accurately.

## Avoid the wrong open-core split

Bad split:

- open toy that cannot complete a real workflow;
- closed schema or evidence format that blocks interoperability;
- cloud-only quickstart;
- public model weights with no data/evaluation contract;
- proprietary validator that makes "open" adapters unverifiable.

Good split:

- a developer can run a complete, honest local workflow;
- contracts and evidence stay portable;
- commercial value comes from operation, scale, security, collaboration,
  integrations, and accumulated permissioned learning.

## Economic packaging hypotheses

Validate before fixing prices:

| Package | Buyer | Unit hypothesis | Value test |
|---|---|---|---|
| Replay assessment | Agency/operator/consultancy | Fixed project or service month | Evidence time, data gaps, scenario result |
| Shadow intelligence | Operations director | Per service/vehicle/month or annual platform | Capacity risk, operator time, measurable baseline |
| Embedded API | Software vendor/broker | Usage plus minimum commit | Faster product delivery and differentiated workflow |
| Enterprise deployment | Large operator/vendor | Annual platform + support | Security, private deployment, SLA, integration |
| Benchmark/registry | Vendor/research team | Free public; paid private runs/team controls | Adoption and comparison workflow |

Pricing should reflect buyer value and procurement reality, not compute cost alone.

## The moat ladder

### Not a moat

- public NTD/GTFS data;
- XGBoost or a transformer;
- OR-Tools/Timefold integration;
- PostgreSQL schema;
- an API wrapper;
- a hash chain;
- a dashboard;
- generic AI language.

### Potential moat

1. **Semantic moat:** mappings between heterogeneous products and a trusted
   canonical model, including hard-won edge cases.
2. **Policy moat:** executable local operating rules, tests, and change history.
3. **Evaluation moat:** comparable model/solver/policy results tied to actual
   information availability and outcomes.
4. **Workflow moat:** embedded review, override, approval, and evidence processes.
5. **Data moat:** permissioned longitudinal decision-to-outcome records with
   sufficiently consistent semantics to improve products.
6. **Ecosystem moat:** external adapters, plugins, benchmarks, and applications
   target Milexium contracts.
7. **Trust moat:** verified security, reliability, domain accuracy, and honest
   claims accumulated over time.

These reinforce each other only if customers retain control and contracts permit
the uses.

## Permission architecture

Data rights are explicit dimensions:

- process for contracted service;
- retain for audit/support;
- use for tenant-specific evaluation/training;
- use for cross-tenant aggregate benchmarks;
- use for generalized models;
- publish de-identified results;
- share with subprocessors.

Default permissions are narrow. Consent/contract changes are versioned. Removing a
tenant's data from future training must have a defined operational process.

## Open-source success metrics

- successful quickstart runs;
- weekly active external workspaces;
- external adapter/plugin packages;
- benchmark reproductions and submissions;
- documentation completion and issue resolution;
- version retention/upgrades;
- conversion to private replay or cloud evaluation;
- contributor diversity;
- time from first install to first verified evidence bundle.

GitHub stars are a secondary signal.

## Defensibility tests

Ask every quarter:

1. Can an incumbent copy the visible feature in one release?
2. What customer-specific learning would still be missing?
3. Does each new integration reduce the cost of the next one?
4. Does outcome history improve a measurable deployment decision?
5. Are external developers building against the contracts?
6. Can customers leave with their data and evidence, while Milexium still has a
   viable business?
7. Is commercial value in reliable operation or artificial lock-in?

If the answer is merely "our model is better," the strategy has regressed.

