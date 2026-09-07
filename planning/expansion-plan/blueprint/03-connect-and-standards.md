# Milexium Connect and transport standards

## Purpose

Milexium Connect converts heterogeneous operational sources into versioned
canonical state without hiding data loss. Its product value is not the number of
format logos on a website; it is reliable mapping, reconciliation, provenance,
validation, and recoverability.

```text
source bytes
  -> immutable landing object + checksum
  -> structural parser
  -> source-specific semantic mapper
  -> canonical validation
  -> reconciliation and reject report
  -> versioned state snapshot/events
```

Every import produces:

- source identity and declared timezone;
- acquisition time and effective data interval;
- checksum and byte size;
- adapter and schema versions;
- accepted, rejected, defaulted, and quarantined row counts;
- field-level mappings and units;
- semantic-loss warnings;
- reconciliation totals;
- the previous successful import and change summary;
- an idempotency key and retry result.

## Standards are complementary

| Source/standard | What it is good for | What it does not establish | Milexium priority |
|---|---|---|---|
| CSV/Excel/vendor export | Fastest route to a real shadow-mode pilot | Stable semantics or quality | P0 |
| GTFS Schedule | Public planned fixed-route service and geography | Private bookings or dispatch decisions | P1 |
| GTFS Realtime | Trip updates, vehicle positions, and service alerts | Full historical operations or DRT booking transactions | P1 where available |
| GTFS Flex | DRT discoverability, zones, service windows, and booking rules | Complete reservation, eligibility, fleet, manifest, or outcome interchange | P1 for service context |
| TCRP Report 210 TDS | Transactional exchange concepts for demand-responsive transportation | Universal vendor adoption | P0 conceptual alignment |
| TODS | Porting scheduled operational plans between products and agencies | Demand-responsive rider transactions | P2 |
| TIDES | Historical vehicle, passenger, fare, and related operations data | Live command-and-control semantics | P2 |
| NeTEx | Rich European planned/reference public transport data | A simple US paratransit booking API | Expansion adapter |
| SIRI | European real-time public transport exchange | Canonical historical decision evidence | Expansion adapter |

GTFS Flex was incorporated into the GTFS specification in March 2024 and describes
DRT patterns through GeoJSON locations, pickup/drop-off windows, and booking rules.
It is an input to Milexium's service context, not a substitute for the operational
request and decision schema. [GTFS Flex documentation](https://gtfs.org/documentation/schedule/examples/flex/)

TCRP Research Report 210 defines a transactional data specification intended to
facilitate interactions among systems that manage demand-responsive transportation.
Milexium should reuse its vocabulary and map departures explicitly rather than
claim to invent the first canonical model.
[National Academies report](https://www.nationalacademies.org/publications/25800)

TODS targets portability of scheduled transit operations between products, while
TIDES targets access to historical operations data. They should have separate
adapters and conformance fixtures.
[TODS](https://tods-transit.org/) ·
[TIDES](https://tides-transit.org/gh-pages/)

For European expansion, NeTEx and SIRI are relevant because EU multimodal travel
information rules identify them for static/planned and real-time public transport
exchange. Supporting them should follow a European customer or partner, not precede
one. [EU delegated regulation](https://eur-lex.europa.eu/legal-content/EN/ALL/?uri=CELEX%3A32017R1926)

## Adapter contract

An adapter implements:

```text
inspect(source) -> SourceProfile
validate_raw(source) -> ValidationReport
map(source, mapping_config) -> CanonicalBatch
reconcile(source, batch) -> ReconciliationReport
incremental_cursor(previous_import) -> Cursor
export(batch, target_version) -> ExportArtifact   # only when supported
```

It declares:

- adapter name and semantic version;
- supported source product/version;
- supported Milexium schema range;
- entities and fields covered;
- incremental/full-import capability;
- deletion and correction semantics;
- timezone, coordinate-reference, units, and identity behavior;
- known semantic gaps;
- fixtures and conformance results.

Vendor names and undocumented fields live under namespaced extensions such as
`extensions.vendor_name.*`. A source field enters the common schema only after its
meaning is stable across valid sources.

## Mapping rules

1. Never silently coerce a missing requested time into a scheduled time.
2. Preserve requested, negotiated, promised, scheduled, predicted, and actual
   timestamps as distinct fields.
3. Store source identifiers and Milexium identifiers separately.
4. Normalize timestamps to UTC while retaining local service date, timezone, and
   DST disambiguation.
5. Retain original units and conversion metadata.
6. Distinguish zero, missing, not applicable, suppressed, and unknown.
7. Quarantine impossible or policy-sensitive records rather than guessing.
8. Treat free text as sensitive by default.
9. Record all defaults and derived fields with transformation lineage.
10. Reconcile counts, service totals, time ranges, and financial totals before an
    import can become active.

## Adapter maturity

- **Experimental:** maps fixtures; breaking changes allowed.
- **Preview:** maps a complete synthetic/reference export; reports semantic loss.
- **Verified:** maps a de-identified real export with operator reconciliation.
- **Supported:** monitored in production with a named version range and response
  commitment.

The public adapter registry should display maturity and last verification date.

## Parallel adapter portfolio

Run independent adapter swarms for:

- strict generic CSV/Parquet/JSON/database import for requests, vehicles, shifts,
  schedules, dispatch, and outcomes;
- GTFS Schedule and GTFS Flex service context;
- GTFS-Realtime streaming, corrections, outages, and replay;
- TIDES and TODS mappings and conformance fixtures;
- NTD and public-agency reporting;
- OSM, routing, weather, traffic, facility, and demographic context;
- authorized incumbent exports;
- NEMT, microtransit, campus, airport, fixed-route, broker, provider, and
  accessibility domain packages.

Every swarm targets the shared adapter contract, preserves source meaning,
reports semantic loss, and contributes fixtures to the certification corpus.
Integration evidence and semantic coverage—not raw format count—measure progress.
