# The 250 GB Milexium data estate

## Target

Build a deliberately composed **250 GB transport intelligence estate** that
supports forecasting, optimization, simulation, standards conformance, semantic
memory, agent environments, replay, and commercial evidence.

The target is total retained project data—not 250 GB of downloads. It includes
source data, canonical forms, high-value derived artifacts, decision episodes,
simulation corpora, and evaluator traces.

## Current local position as of 23 July 2026

| Collection | Binary size | Decimal size | Files | Content |
|---|---:|---:|---:|---|
| `realdata/raw_tlc` | 37.109 GiB | 39.846 GB | 88 | NYC high-volume for-hire vehicle source files |
| `realdata/raw_tlc_taxi` | 20.614 GiB | 22.134 GB | 334 | NYC yellow/green taxi source files |
| `realdata/panels` | 1.535 GiB | 1.648 GB | 258 | Derived analytical panels |
| `realdata/output` | 0.197 GiB | 0.212 GB | — | Generated outputs |
| Entire `realdata` tree | 59.46 GiB | 63.84 GB | 747 | Source and derived data |

Documented coverage also includes approximately 1.586 billion FHVHV trips,
555 million Chicago TNP trips aggregated by zone-hour, 26.3 million NYC
accessible-dispatch trips in aggregate form, NTD, MTA, weather, census, and
economic context.

The C: drive now has approximately **314.2 GiB / 337.3 GB free**. Expanding the
project from 63.84 GB to 250 GB requires approximately **186.2 GB** of additional
retained data and leaves approximately **151 GB** free before temporary build,
database, model, and index files. That is feasible, but transformation jobs must
use bounded scratch space and delete reproducible intermediates after their
artifact hashes are recorded.

## Exact 250 GB portfolio

| Data domain | Target retained size | Intelligence enabled |
|---|---:|---|
| Existing public mobility corpus | 64 GB | Large-scale ingestion, forecasting, geographic transfer, temporal analysis |
| Consented operator operations | 55 GB | Real request-to-outcome chain, policy, dispatch, overrides, validation |
| Standards and live-feed archive | 25 GB | GTFS/Flex/Realtime/TIDES/TODS conformance, streaming, outage and correction replay |
| Road, routing, and travel-time estate | 25 GB | Network feasibility, routing, disruption, travel-time matrices and graph models |
| Simulation and scenario worlds | 18 GB | Discrete-event twins, synthetic agencies, disruption curricula, policy evaluation |
| Weather, traffic, facility, accessibility, demographic context | 12 GB | Exogenous drivers, facility queues, equity and resilience analysis |
| Features, point-in-time panels, and replay fixtures | 20 GB | Leakage-safe learning, deterministic replay, fast experiments |
| Semantic episodes, embeddings, and retrieval indexes | 10 GB | Precedent search, case memory, anomaly review, agent context |
| Experiment, solver, verifier, and agent traces | 9 GB | Learning-guided optimization, Forge memory, evaluator regression |
| Dial-a-ride, optimization, and formal benchmark corpora | 4 GB | Solver correctness, exact/approximate comparisons, conformance |
| Data manifests, schemas, metrics, checksums, and compact evidence | 8 GB | Reproducibility, governance, version history, selected reports/artifacts |
| **Total** | **250 GB** | Full transport-intelligence research and product estate |

The 8 GB manifest/evidence allocation includes retained compact artifacts and
versioned metadata, not duplicated raw datasets. If these artifacts remain
smaller, capacity shifts to operator operations or simulation worlds.

## Directory and storage layout

```text
data/
  catalog/               Dataset contracts, rights, hashes, inventories
  raw/                   Immutable downloaded or received objects
    public/
    partner/
  quarantine/            Untrusted inputs awaiting validation
  canonical/             Typed, reconciled, bitemporal domain records
  features/              Point-in-time feature snapshots
  networks/              OSM, graphs, matrices, closures, routing artifacts
  standards/             GTFS/Flex/Realtime/TIDES/TODS fixtures and archives
  simulation/            Worlds, scenarios, trajectories, calibration
  semantic/              Case documents, embeddings, index generations
  experience/            Agent, solver, verifier, and experiment traces
  benchmarks/            Frozen train/validation/test and adversarial suites
  evidence/              Replay manifests, reports, proof/certificate artifacts
  scratch/               Bounded, reproducible, automatically expired
```

Raw objects are immutable and content-addressed. Canonical and derived datasets
identify source hashes, code version, schema, parameters, and creation time.
Scratch data has no unique information and is deleted automatically.

## Acquisition manifest

No download enters the estate without:

```yaml
dataset_id:
owner_and_source:
license_and_commercial_rights:
decision_tasks_enabled: []
geography:
time_coverage:
expected_download_gb:
expected_expanded_gb:
expected_retained_gb:
schema_and_format:
sensitive_fields:
update_frequency:
source_checksum:
canonical_contract:
quality_tests: []
acceptance_threshold:
retention_and_deletion:
derived_artifacts: []
```

This does not constrain acquisition volume; it ensures every byte has a product,
scientific, benchmark, or verification purpose.

## Consented operator allocation: 55 GB

The operator estate should preserve the complete operational chain:

- request received time and channel;
- requested and negotiated pickup/drop-off windows;
- origin/destination under the agreed privacy representation;
- subscription and standing-order linkage;
- equipment, capacity, assistance, companion, eligibility, and service
  constraints;
- scheduling versions and objective/policy versions;
- run, vehicle, provider, and driver assignments;
- dispatch revisions, messages, and manual overrides with reason codes;
- vehicle location and arrival/boarding/drop-off signals;
- cancellation timing and attribution;
- no-show classification, denials, missed trips, and incomplete service;
- complaint, incident, and downstream service outcomes where authorized;
- KPI definitions, operating calendars, and SOP/policy versions;
- source identifiers, time zones, export timestamps, and correction history.

Suggested internal partition:

| Operator data layer | Allocation |
|---|---:|
| Encrypted immutable source exports | 20 GB |
| Canonical bitemporal state | 12 GB |
| Point-in-time features and outcomes | 8 GB |
| Replay and evaluation snapshots | 6 GB |
| Telemetry/vehicle traces | 6 GB |
| Evidence, mappings, and quality artifacts | 3 GB |

Size is a reservation. Field completeness, linkage, time semantics, rights, and
outcomes determine value.

## Standards and feed archive: 25 GB

Cover:

- GTFS Schedule and Flex examples across diverse service patterns;
- GTFS-Realtime trip updates, vehicle positions, alerts, duplicates, lateness,
  resets, and outages;
- TIDES/TODS fixtures and mappings;
- representative NTD and agency exports;
- corrupted and adversarial conformance fixtures;
- historical snapshots for schema and service evolution;
- time-zone, daylight-saving, calendar, shape, stop, and identifier edge cases.

The output is both data and a reusable adapter-certification corpus.

## Road and routing estate: 25 GB

Retain selected OSM extracts, normalized networks, contraction/customization
artifacts, accessibility attributes, time-dependent costs, closures, zones,
facility access points, and sampled travel-time matrices.

Represent road-graph version in every decision snapshot. Raw map extracts and
derived routing graphs remain separately reproducible.

## Simulation and world data: 18 GB

Generate:

- synthetic agency families across fleet, demand, geography, and policy scales;
- static and dynamic dial-a-ride instances;
- cancellations, no-shows, driver absence, vehicle failure, road closure,
  facility congestion, weather, and communications-outage scenarios;
- event-level trajectories from multiple policies and solvers;
- adversarial state-machine and replay sequences;
- latent world-model training and held-out trajectories;
- simulator calibration targets and sim-to-real discrepancies.

Each simulated record is marked synthetic and identifies its world generator,
seed, policy, simulator version, and calibration source.

## Feature and replay estate: 20 GB

Use point-in-time tables partitioned by task, geography, service date, and
vintage. A feature row records availability time, source version, transformation
hash, and entity keys. Frozen replay fixtures include original state cutoffs,
policy/model/solver/index versions, outputs, and later outcomes.

Materialize only reused or expensive features. Cheap transformations remain
virtual and reproducible.

## Semantic and experience estate: 19 GB

### Semantic allocation: 10 GB

Embed high-value decision episodes, policy passages, evidence records,
incidents, mapping precedents, runbooks, and benchmark cases. Maintain exact
metadata in PostgreSQL and multiple rebuildable index generations.

For 1,536-dimensional vectors:

| Vectors | float32 source | Ideal 2-bit codes | Ideal 4-bit codes |
|---:|---:|---:|---:|
| 1 million | 6.14 GB | 0.38 GB | 0.77 GB |
| 10 million | 61.44 GB | 3.84 GB | 7.68 GB |
| 100 million | 614.4 GB | 38.4 GB | 76.8 GB |

The 10 GB allocation supports roughly one to ten million compressed semantic
cases depending on bit width, metadata, generations, and whether float source
vectors are regenerated or retained elsewhere.

### Experience allocation: 9 GB

Retain compact:

- solver node/branch/propagation summaries and instance fingerprints;
- agent tool/action/reward/verifier traces;
- experiment hypotheses, diffs, costs, metrics, and outcomes;
- compiler rewrites, kernel schedules, and hardware counters;
- failure clusters, counterexamples, and adversarial cases;
- accepted and rejected memory/model/policy deltas.

Large logs are normalized, compressed, sampled with declared policies, and
linked to immutable full artifacts when required.

## Formats and compression

- Parquet with Zstandard for analytical tables;
- Arrow for interchange and streaming batches;
- GeoParquet or canonical geometry plus explicit CRS for spatial data;
- compact binary formats for indexes and model artifacts;
- JSON only for human-scale manifests and portable evidence;
- partitioning aligned to common pruning keys;
- dictionary encoding for repeated vendor, zone, service, and policy values;
- no lossy compression for canonical facts unless the error contract is part of
  the field definition;
- controlled lossy compression for telemetry, embeddings, or simulation only
  with measurable downstream impact.

## Deduplication and lifecycle

Content hashes prevent duplicate raw objects. The catalog tracks logical
datasets separately from physical objects. Derived artifacts specify whether
they are:

- **irreplaceable:** authorized source exports and signed external evidence;
- **expensive but reproducible:** routing graphs, embeddings, trained models,
  large simulation corpora;
- **cheaply reproducible:** ordinary panels, caches, temporary conversions;
- **required for audit:** decision-time snapshots, promotion evidence, proof
  objects, incident records.

Eviction removes cheap reproducible artifacts first and never silently removes
audit or contractual records.

## Data quality and leakage controls

Every dataset runs:

- schema, type, range, null, uniqueness, and referential checks;
- temporal ordering and availability checks;
- unit, coordinate, time-zone, and calendar validation;
- reconciliation against published totals or source controls;
- duplicate, correction, and late-arrival classification;
- sensitivity and re-identification assessment;
- license and commercial-use validation;
- train/test entity and temporal leakage checks;
- transformation determinism and hash verification.

## 250 GB completion evidence

The target is achieved when:

1. cataloged retained physical bytes total approximately 250 GB;
2. every object has ownership, rights, purpose, checksum, and lifecycle;
3. every major Milexium product has benchmark and replay data;
4. the consented operator chain connects request to outcome;
5. source, canonical, feature, simulation, semantic, and experience zones are
   reproducibly linked;
6. hidden and adversarial evaluation partitions exist;
7. the entire estate can be inventoried, validated, partially rebuilt, and
   selectively deleted through automated commands;
8. the system reports free-space, scratch, database, index, and artifact growth
   before executing large transforms.
