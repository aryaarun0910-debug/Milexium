# Security, privacy, and AI governance

## Risk posture

Milexium may process precise locations, recurring travel patterns, disability-
related operational needs, staff schedules, and potentially health-related NEMT
information. The architecture must minimize what it receives and make deployment
risk proportional to the use case.

Do not call the product HIPAA compliant, ADA compliant, SOC 2 compliant, or
litigation-ready without the applicable legal, contractual, technical, and audit
conditions.

## Threat model

Priority threats:

1. Cross-tenant access to rider, fleet, or policy data.
2. Over-privileged model/solver plugins exfiltrating state.
3. Sensitive fields entering logs, traces, benchmark artifacts, or exports.
4. Malicious or malformed imports changing operational decisions.
5. Compromised credentials or API tokens.
6. Insider access to precise recurring rider locations.
7. Replay or evidence manipulation.
8. Model artifact or dependency supply-chain compromise.
9. Denial of service through large imports or optimization instances.
10. Unsafe recommendations during stale-data or partial-system failure.
11. Re-identification of supposedly anonymized trip data.
12. Policy/model alias changes without approval or rollback.

Each threat maps to preventive, detective, recovery, owner, and test controls.

## Data minimization

- Store operational requirements, not diagnoses, unless a legitimate workflow
  explicitly requires more.
- Tokenize identity separately from operational facts.
- Generalize or redact precise locations in analytics and support workflows.
- Treat free text as sensitive and exclude it from general model features.
- Separate production data, support access, benchmark data, and public artifacts.
- Define retention and deletion per class, tenant, contract, and legal need.
- Do not retain raw imports indefinitely by default merely because storage is cheap.
- Make training permission independent from service-processing permission.

HIPAA de-identification is not achieved by deleting names alone. HHS describes
Safe Harbor and Expert Determination as the two Privacy Rule methods and notes
that combinations of data can create identification risk.
[HHS de-identification guidance](https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html)

For NEMT, determine whether Milexium is handling PHI for a covered entity or
business associate in each relationship. Business-associate agreement terms must
authorize uses such as de-identification; do not infer permission from technical
access. [HHS guidance](https://www.hhs.gov/hipaa/for-professionals/faq/544/may-a-health-information-organization-de-identify-information/index.html)

## Tenant and access controls

- Tenant ID on every operational record and object path.
- Database row-level security plus application authorization.
- Default-deny roles and least privilege.
- Separate service identities for import, model, solver, export, and support.
- Short-lived credentials and managed secrets.
- MFA/SSO for administrative access when commercialized.
- Time-bounded, approved, logged support access.
- Field-level restrictions for identity and sensitive operational requirements.
- Automated negative tests for cross-tenant access at API and database layers.

Database owners can bypass typical RLS behavior; deployment roles and migration
processes must account for this. RLS is defense in depth, not a checkbox.

## Encryption and key management

- TLS for data in transit.
- Managed encryption at rest for database, object storage, backups, and queues.
- Separate key administration from data access where required.
- Rotation, revocation, and recovery procedures.
- Artifact signing keys distinct from encryption keys.
- No keys or credentials in source, model artifacts, logs, or evidence payloads.

## Evidence integrity

- Append-only application events backed by database permissions.
- Sequence and hash-chain verification.
- Periodic signed checkpoints stored in a separate trust boundary.
- Immutable/retention-locked object storage only where contractually justified.
- Independent export verifier.
- Audit of policy, model alias, schema, and access changes.

Integrity controls prove recorded content has not changed after a checkpoint; they
do not prove input truth or legal sufficiency.

## AI and optimization governance

Use the NIST AI RMF's Govern, Map, Measure, and Manage structure as a voluntary
operating framework. NIST emphasizes lifecycle governance, ongoing monitoring,
validation, documentation, and interpretation of outputs in context.
[NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework) ·
[AI RMF Core](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)

### Govern

- named owners for task, data, model, policy, and deployment;
- intended/prohibited use;
- approval and change control;
- incident and rollback procedures;
- third-party plugin risk;
- periodic review.

### Map

- affected riders, operators, drivers, agencies, providers, and public;
- decision context and consequence;
- information availability;
- legal/policy dependencies;
- failure and abuse scenarios.

### Measure

- forecast and calibration performance;
- feasibility and solver validity;
- outcome and override metrics;
- slice analysis;
- reliability, latency, and cost;
- evidence completeness;
- human comprehension and workload.

### Manage

- risk thresholds and response;
- shadow/advisory/controlled deployment tier;
- abstention/fallback;
- monitoring and promotion;
- rollback and disable;
- incident learning.

## Human oversight

Each consequential workflow defines:

- authorized decision owner;
- when human approval is mandatory;
- what evidence is shown before approval;
- override reason and downstream impact;
- escalation path;
- prohibited automation;
- response when no feasible plan exists;
- how overrides feed evaluation without being assumed correct labels.

The UI must make uncertainty, stale data, missing constraints, solver status, and
simulation status visible. Dark patterns that steer a dispatcher toward accepting
the model undermine genuine oversight.

## Secure development

Align the engineering program with NIST SSDF:

- protected source and branch controls;
- dependency locks and vulnerability scanning;
- secret scanning;
- signed/reproducible releases where practical;
- code review and security tests;
- isolated build artifacts;
- incident/vulnerability intake;
- supported-version policy;
- backup and restore exercises.

[NIST SSDF 1.1](https://www.nist.gov/publications/secure-software-development-framework-ssdf-version-11-recommendations-mitigating-risk)

Use OpenTelemetry for vendor-neutral traces, metrics, and logs, but apply explicit
redaction and attribute allowlists before export.
[OpenTelemetry documentation](https://opentelemetry.io/docs/)

## Deployment tiers

| Tier | Behavior | Minimum evidence |
|---|---|---|
| Local/public demo | Fictional or public aggregate data | No sensitive data; reproducible install |
| Offline customer replay | Read-only export in isolated workspace | Data agreement, access controls, deletion certificate |
| Hosted shadow mode | Customer data, no live control | Tenant isolation, monitoring, backups, incident response |
| Advisory operations | Live recommendations, human approval | SLOs, rollback, stale-state detection, audit and training |
| Controlled execution | Authorized changes to operations | Strong change control, safe degradation, drills, customer approval |

Progression is per tenant and workflow, not a company-wide marketing label.

## Procurement evidence pack

- architecture and data-flow diagrams;
- data inventory/classification and retention;
- threat model and control mapping;
- subprocessor and deployment list;
- encryption/key management summary;
- access-control matrix;
- secure-development policy;
- vulnerability disclosure and incident process;
- backup/restore results;
- model/policy governance;
- accessibility statement;
- current certifications with exact scope, if any;
- known gaps and remediation plan.

