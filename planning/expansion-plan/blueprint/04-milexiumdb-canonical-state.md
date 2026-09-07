# MilexiumDB: canonical transport state

## Definition

MilexiumDB is the domain data plane and schema contract for transport decisions.
It is not a custom database engine. PostgreSQL/PostGIS should remain the production
system of record, with object storage for source and artifact blobs.

Its strategic job is to make models, solvers, applications, and evaluations
interoperate against the same meanings.

## Canonical bounded contexts

### Identity and tenancy

`Tenant`, `Organisation`, `Service`, `SourceSystem`, `ExternalIdentity`,
`Actor`, `Role`, `Permission`.

Every sensitive or operational row carries a tenant ID. Cross-tenant aggregation
uses an explicit, permissioned derived-data process—not an absent tenant filter.

### Service and geography

`ServiceArea`, `Zone`, `Stop`, `Facility`, `Depot`, `OperatingCalendar`,
`TravelTimeMatrix`, `RoadNetworkVersion`.

Geometry records include source, coordinate reference, validity interval, and
precision. A facility such as a dialysis center is not itself a rider diagnosis.

### Demand and people

`ServiceRequest`, `RequestLeg`, `OperationalRequirement`, `Companion`,
`SubscriptionPattern`, `RequestedWindow`, `NegotiatedWindow`, `Cancellation`,
`NoShowClassification`.

The core should avoid storing clinical diagnosis. It needs the minimum operational
requirements required to provide a safe trip, such as capacity/equipment and
boarding assistance, with field-level access controls and retention.

### Supply

`Vehicle`, `CapacityProfile`, `Equipment`, `Driver`, `Shift`, `Break`,
`Availability`, `Provider`, `DepotAssignment`.

Capacity is multidimensional: seats, wheelchair positions, stretcher capability,
companions, and incompatible combinations cannot be flattened to one integer.

### Plan and execution

`ScheduleRun`, `Manifest`, `VehicleRun`, `StopAction`, `Assignment`,
`DispatchRevision`, `VehiclePosition`, `PickupOutcome`, `DropoffOutcome`,
`ServiceException`.

### Intelligence and policy

`FeatureSnapshot`, `ModelVersion`, `ForecastVintage`, `PolicyVersion`,
`ConstraintEvaluation`, `ObjectiveDefinition`, `SolverVersion`,
`Decision`, `Alternative`, `Override`.

### Evidence and evaluation

`EvidenceEvent`, `Artifact`, `ReplayRun`, `MetricDefinition`, `MetricResult`,
`DataQualityResult`, `Approval`, `Incident`.

## Temporal model

Milexium must answer two different questions:

- What was believed to be true at decision time?
- What do we now know was actually true?

Use bitemporal concepts:

- **valid time:** when a fact applies in the transport operation;
- **system time:** when Milexium received or recorded that version.

A correction never overwrites the historical version used by a prior decision.
Each decision points to an immutable state snapshot or a deterministic set of
versioned records and cut-off timestamps.

Required time fields are explicit:

```text
requested_at
requested_pickup_window
negotiated_pickup_window
scheduled_pickup
predicted_pickup_as_of
actual_arrival
actual_boarding
recorded_at
source_effective_at
```

## Identity

Use Milexium-generated opaque IDs internally. Maintain an `external_identities`
table keyed by tenant, source system, entity type, source ID, and valid interval.
Never assume vehicle `12` or rider `42` means the same thing across imports.

Identity merges and splits are versioned administrative decisions with evidence.

## State snapshot

A task input references:

```json
{
  "snapshot_id": "sts_...",
  "tenant_id": "ten_...",
  "as_of": "2026-07-23T06:00:00Z",
  "service_date": "2026-07-23",
  "schema_version": "0.2.0",
  "source_imports": ["imp_..."],
  "policy_version": "pol_...",
  "content_hash": "sha256:..."
}
```

Large state is not duplicated into each record. The snapshot contains stable
references and a content manifest. Canonical JSON is used only where byte-stable
hashing is required; transactional data remains typed relational data.

## Evidence events

Use a CloudEvents-compatible envelope where useful:

- `id`, `source`, `specversion`, `type`;
- `subject`, occurrence `time`, data content type;
- tenant, aggregate, sequence, trace, actor, schema, and correlation extensions;
- canonical payload hash, previous event hash, and artifact references.

CloudEvents standardizes common event metadata and requires a producer-scoped
unique combination of source and ID. Milexium adds domain sequencing and evidence
fields rather than inventing incompatible generic metadata.
[CloudEvents specification](https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md)

Hash chains are independently verifiable evidence of mutation or omission within a
known chain. They do not prove that source data was true, that an event was never
withheld before ingestion, or that a decision was lawful.

## Data classifications

| Class | Examples | Default handling |
|---|---|---|
| Public | GTFS, NTD aggregates, public weather | Reproducible source license and checksum |
| Internal | model metrics, synthetic tenant results | Authenticated, normal retention |
| Customer confidential | schedules, fleet, staff, operating policies | Tenant isolation, encryption, limited access |
| Sensitive personal | rider identity, precise recurring locations, assistance needs | Field-level restrictions, audit, minimum retention |
| Potential PHI | health-related NEMT trip/payment context | Contract/legal determination, BAA where applicable, strict environment |
| Secrets | credentials, signing/encryption keys | Secret manager; never database payloads or logs |

## Data quality contract

Each canonical entity has:

- JSON Schema and generated typed model;
- relational constraints;
- cross-entity invariants;
- temporal and range rules;
- sensitivity classification;
- source lineage requirements;
- example and counterexample fixtures;
- backward-compatibility tests.

An import cannot become the active state if blocking reconciliation or invariant
checks fail. Operators can explicitly approve bounded exceptions, which become
evidence events.

## Schema governance

- Use semantic versions while the public API is defined; `0.y.z` remains unstable.
- Maintain compatibility matrices for SDK, API, adapters, models, policies, and
  solvers.
- Add fields backward-compatibly; never reuse field meanings.
- Deprecate with telemetry and a migration path.
- Publish decision records for contested ontology changes.
- Accept extensions without promising that all extensions affect every task.

[Semantic Versioning](https://semver.org/) and
[JSON Schema 2020-12](https://json-schema.org/specification) provide the public
versioning and validation foundations.

## Proof that MilexiumDB is valuable

The schema is not validated by completeness of its ERD. It is validated when:

1. two heterogeneous sources map with documented semantic loss;
2. one task can swap model implementations without remapping source data;
3. one replay can reconstruct the original information horizon;
4. an operator confirms that requested, negotiated, scheduled, and actual outcomes
   remain faithful to their process;
5. a new application consumes state without importing vendor-specific code.

## Semantic state is a derived projection

MilexiumDB may expose a semantic index for analogous-case retrieval, evidence
search, anomaly review, and cold-start features. The relational state and
immutable transition history remain authoritative. Vector entries are
rebuildable projections keyed to opaque handles, embedding versions, and index
generations.

State-machine guards, authorization, capacity constraints, official metrics, and
audit truth never depend on nearest-neighbor results. See
[Semantic state, TurboVec, and scientific R&D](16-semantic-state-and-turbovec.md)
for the consistency, safety, benchmarking, and vendoring contract.
