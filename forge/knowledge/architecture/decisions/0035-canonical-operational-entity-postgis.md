# ADR-0035: Request-independent operational entities + PostGIS geometry (closing the ADR-0031 gap)

- **Status:** Accepted
- **Date:** 2026-07-24
- **Packet:** MX-A-OPS-ENTITY-002 (Program A + C follow-up)

## Context

ADR-0031 surfaced the most important finding of Phase 3's Connect work: the
canonical model is **entirely rider-request-keyed**, but GTFS-Realtime — the
most widely deployed transit-integration surface in the world — is
`(trip, stop, vehicle)`-keyed operational telemetry with **no rider request**.
The first-cut adapter could therefore only squash it onto `Outcome` via a
**synthetic `request_id` referencing no ServiceRequest**, and `Outcome` had no
operational-context fields, so position, occupancy, status, stop/route identity
were all semantic loss. TODS/NeTEx were deferred for the same reason rather than
half-built.

The honest fix is a canonical entity family, not a better adapter.

## Decision

**Two new request-INDEPENDENT canonical entities** in `themis/canonical/`:

- **`VehicleObservation`** — one vehicle observed in motion: `vehicle_ref`,
  `trip_ref`, `route_ref`, `stop_ref`, `current_status`, `latitude`/`longitude`,
  `bearing`, `speed`, `occupancy_status`, `occupancy_percentage`, plus
  bitemporal `observed_at` (valid time, the feed/vehicle epoch — unambiguously
  UTC) and `recorded_at` (transaction time).
- **`StopTimeObservation`** — one stop of one trip: `stop_ref`, `stop_sequence`,
  `schedule_relationship`, `predicted_arrival_at`/`predicted_departure_at`,
  `observed_arrival_at`/`observed_departure_at`, and arrival/departure delays.

Three design calls worth recording:

1. **Source refs are plain strings, not canonical typed ids.** A GTFS
   `vehicle_id`/`trip_id`/`stop_id` names an *external agency's* entity, not a
   Milexium `Vehicle` aggregate — typing them as `VehicleId` would repeat the
   very category error this entity exists to remove.
2. **`ObservationId` is the record's OWN primary key** (new typed UUIDv7 id) —
   the deliberate counterpoint to ADR-0031's synthetic `request_id`, which was a
   foreign key to a row that did not exist.
3. **Predicted and observed times are separate fields.** GTFS-RT supplies
   *predictions*; those land in `predicted_*` while `observed_*` stays `None`,
   preserving the predicted-vs-actual discipline `ForecastVintage` keeps —
   instead of coercing a prediction into `Outcome.on_time` as before.

**Portability preserved (ADR-0002), geometry separately versioned.** The base
`sql/schema_v0_1.sql` gains `vehicle_observations` + `stop_time_observations`
with position as **plain `REAL` lat/lon and no PostGIS type**, so it still runs
unmodified on SQLite (verified) and Postgres. All spatial constructs live in a
new Postgres-only `sql/postgis_postgres.sql` — `CREATE EXTENSION postgis`, a
`geometry(Point, 4326)` column, population via
`ST_SetSRID(ST_MakePoint(lon, lat), 4326)`, and a GiST index — applied only by
the new store, **exactly the separation `rls_postgres.sql` established**.

**`themis/canonical/observation_store.py`** — a `PostgisObservationStore`
targeting the **containerized PostGIS on host port 5433** (ADR-0032), additive
to and not modifying `postgres_storage.py` (which targets the native 5432
instance with RLS). It applies the portable schema, then the geometry extension,
into a disposable `mx_<uuid>` schema dropped with `CASCADE`. It inserts only the
portable columns and **derives** the geometry from the stored lat/lon, so the
REAL→geometry derivation itself is what the spatial round-trip proves;
`observations_within()` reads back via `ST_DWithin` on a `::geography` cast
(true metric distance on WGS84).

**`GtfsRealtimeAdapter` re-mapped** onto the new family: `VehiclePosition` →
`VehicleObservation`, `TripUpdate.stop_time_update` → `StopTimeObservation`,
`Alert` still quarantined. The `STOPPED_AT`-only gate is **gone** — an in-transit
position is precisely what a telemetry entity is for.

## Consequences

- **The squash is eliminated, measured on the real samples** (independently
  re-run during review):

  | Sample | Before (ADR-0031) | After |
  |---|---|---|
  | MBTA `VehiclePositions.pb` | 251 `Outcome`s w/ synthetic id, **314 quarantined** | **567/567 `VehicleObservation`s, 0 quarantined** |
  | Apache-2.0 `.asciipb` | 3 prediction `Outcome`s | **5/5 `StopTimeObservation`s** |

  No synthetic `request_id` is minted anywhere. Residual loss is now genuinely
  homeless optional detail (`direction_id`, `start_date`, vehicle `label`/
  `license_plate`, `odometer`, `congestion_level`, trip-level `delay`,
  prediction `uncertainty`) — still reported as `dropped`/`unmapped_extension`,
  never silently discarded.
- **PostGIS is in real use, not just installed.** 2 spatial conformance tests
  **ran** (not skipped) against the live container, including a tenant-scoped
  spatial query; they skip cleanly where psycopg/the container are absent.
- The two entities are exported through `themis/canonical/__init__.py` and
  **added to the generated contract layer** (`talos/contracts/` now emits 14 entities),
  since external producers map onto these rather than the rider-request entities.
- **Not built (Specified):** the *scheduling* operational family TODS needs
  (`Block`/`RunCut`/`PieceOfWork`) is a different family again and remains
  deferred; no store method persists `StopTimeObservation` yet (only
  `VehicleObservation` has the spatial round-trip); RLS policies are not applied
  to the observation tables by this packet. Status remains **Demonstrated**
  (open public real-time data, not consented operator data).
