# Go to market and ecosystem

## Beachhead remains paratransit

Initial buyer hypothesis:

- US small-to-mid-sized ADA paratransit agency or contracted operator;
- existing scheduling/dispatch product;
- operations director accountable for service quality and cost;
- scheduling manager and ADA/compliance coordinator as daily stakeholders;
- IT, privacy/security, procurement, and possibly labor as gates.

Initial product:

> Read-only shadow import and temporal replay that helps the operator forecast
> capacity, reconstruct exceptions, compare plans, and export structured evidence
> without surrendering live dispatch control.

This is narrower and safer than selling the entire platform vision.

## Land-and-expand

```text
data readiness assessment
    -> historical replay
    -> recurring shadow forecasts
    -> advisory plan comparison
    -> approved decision support
    -> controlled optimization for bounded workflows
    -> embedded/vendor API
```

Each step has an independent success gate. A customer can remain at replay or
forecasting without adopting Milexium scheduling.

## Design-partner package

### Input request

Start with the minimum:

- 30-90 days of requests and revisions;
- requested, negotiated, and scheduled times;
- vehicle/equipment and driver/shift availability;
- manifests and dispatch revisions;
- pickup/drop-off outcomes and exception classifications;
- operating policy and metric definitions;
- source-system/version documentation.

Accept de-identified or limited data where feasible. If exact location and times
are required for routing, use an appropriate controlled environment rather than
pretending coarse de-identification preserves the task.

### Delivery

- data-quality and semantic-loss report;
- baseline metric reconstruction;
- point-in-time forecast evaluation;
- replay under an agreed alternative;
- evidence package for selected exceptions;
- security/deletion report;
- limitations and next-step recommendation.

### Pre-agreed success criteria

Choose a small set with the operator:

- percentage of records reconstructable;
- time to answer a disputed trip;
- agreement on denial/missed-trip classification;
- prediction error and interval calibration;
- on-time pickup or service metric in shadow replay;
- deadhead/overtime/utilization;
- dispatcher review time and override rate;
- evidence completeness.

A technically successful pilot can reveal that the product is commercially
unnecessary. Record that result.

## No-outreach adoption strategy

No public artifact replaces customer discovery, but Milexium can create inbound
technical credibility:

### Developer loop

1. Publish the canonical schema, validator, SDK, and local quickstart.
2. Let developers map CSV/GTFS Flex and get a quality report immediately.
3. Run a complete reference forecast/solver/evidence/replay flow.
4. Invite adapter, solver, and model plugins.
5. Convert teams needing private data, scale, or support to cloud/private replay.

### Research loop

1. Publish the benchmark protocol and baseline results.
2. Release reproducible negative results as well as wins.
3. Invite external submissions and replication.
4. Collaborate with transport, operations-research, accessibility, and public-
   administration researchers.
5. Turn benchmark adoption into platform/plugin adoption.

### Consultancy/integrator loop

1. Give transport consultants a repeatable data-readiness and replay toolkit.
2. Preserve their client relationship and allow branded reports.
3. Sell supported private execution, adapters, and evidence retention.
4. Learn recurring schema and policy gaps without competing for every engagement.

### Vendor loop

1. Offer the benchmark/evidence harness before asking a dispatch vendor to replace
   any component.
2. Provide model and solver plugin interfaces.
3. Demonstrate an embedded evidence API on vendor-controlled data.
4. Sell white-label/private deployment only after technical and channel fit.

## Distribution artifacts

Build one excellent artifact per audience:

| Audience | Artifact | Conversion |
|---|---|---|
| Operator | Redacted incident replay/evidence case | Data-readiness assessment |
| Developer | Ten-minute SDK quickstart | Private workspace/cloud |
| Researcher | Reproducible benchmark | Submission/collaboration |
| Consultant | Local assessment toolkit | Supported deployment |
| Vendor | Conformance/evidence API demo | Embedded evaluation |
| YC/investor | End-to-end decision-to-outcome demo | Credibility and funding |

Avoid multiple shallow demos.

## Category creation

Lead with the problem and workflow:

- reconstructable transport decisions;
- policy-aware model/solver deployment;
- temporal replay;
- evidence tied to outcomes.

Use "transport decision infrastructure" as the category only after showing the
workflow. "Intelligence layer" alone is too abstract.

## Expansion adapters

Each new adapter needs:

| Gate | Required proof |
|---|---|
| User | Named user with repeated decision problem |
| Buyer | Identified budget owner and buying trigger |
| Data | Obtainable, lawful inputs and outcomes |
| Domain | Explicit constraints, objectives, policies, terminology |
| Evaluation | Baseline and success metric |
| Reuse | Majority of value uses shared core rather than a new product |
| Channel | Reachable design partner or integration partner |

Suggested order after paratransit evidence:

1. NEMT only when PHI/payer/provider workflow is understood.
2. Microtransit where DRT schema and solver reuse are high.
3. Campus shuttle or airport landside only with a concrete operational partner.
4. Fixed-route intelligence where current public datasets support a genuinely
   distinct product task.

Do not show six empty adapter tiles.

## Partnerships

Potential partners:

- transport consultancies and implementation firms;
- state/regional transit associations;
- accessibility and mobility organizations;
- university operations-research/transit labs;
- standards communities such as MobilityData, TIDES, and TODS;
- mapping/travel-time providers;
- incumbent vendors willing to expose or consume evidence APIs;
- cloud/security partners after customer demand.

Contribution to a standard or open validator is more credible than merely listing
the standard as supported.

## Procurement strategy

Start with read-only, time-bounded work:

- no live control;
- least data required;
- customer-selected deployment boundary;
- fixed retention/deletion;
- documented subprocessors;
- clear outcome and exit;
- exportable evidence and schema;
- no automatic renewal into a broader data right.

This reduces risk while Milexium earns operational trust.

## Commercial learning system

For every outreach, inbound user, and pilot, record:

- segment and role;
- problem hypothesis;
- current workflow and products;
- frequency/cost of problem;
- evidence/data available;
- procurement and security blockers;
- desired metric;
- willingness to act/pay;
- objection;
- next experiment.

Feed recurring semantic, policy, and workflow gaps into the product backlog. Do not
mistake feature requests from non-buyers for a roadmap.

