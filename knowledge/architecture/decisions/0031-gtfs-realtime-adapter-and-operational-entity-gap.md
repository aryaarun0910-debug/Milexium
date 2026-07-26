# ADR-0031: GTFS-Realtime adapter, and the canonical operational-entity gap it surfaced

- **Status:** Accepted
- **Date:** 2026-07-24

## Context

Phase 3 item B widens the "integrate any transport source" claim with a
**GTFS-Realtime** adapter — the most widely deployed real-time transit
standard. Building it surfaced a genuine gap in the canonical model, which is
the more important output than the adapter itself.

## Decision

`app/connect/gtfs_realtime.py` — `GtfsRealtimeAdapter` against the existing
`SourceAdapter` contract (ADR-0007), matching the sibling adapters' quarantine +
semantic-loss discipline.

- **Reader** (`read_gtfs_realtime_feed` / `feed_message_to_rows`) parses a
  `FeedMessage` via Google's official `gtfs-realtime-bindings` (added to
  `pyproject.toml` with `protobuf`), flattening to plain dicts — one per
  `VehiclePosition`, one per exploded `TripUpdate` stop_time_update. Supports
  binary `.pb` and text `.asciipb`. The bindings import is guarded so `parse()`
  and all mapping tests run **without** the protobuf dependency; only the reader
  needs it. GTFS-RT epoch timestamps are unambiguous UTC — no timezone coercion,
  a fidelity win over the naive-local CSV adapters.
- **Target canonical concept: `Outcome`** (the only entity modeling an
  operational *result*). A record is emitted only from a signal carrying
  observed/decided content: `VehiclePosition` `STOPPED_AT` →
  `Outcome(served=True, actual_pickup_at=ts)`; `TripUpdate` stop `SKIPPED` →
  `Outcome(served=False)`; a predicted delay → `Outcome(on_time=…)` (±60s
  adapter threshold, `actual_pickup_at=None` because a prediction is not an
  observation). In-transit telemetry, content-free stops, and `Alert`s are
  quarantined with reasons that name the gap.
- Real samples acquired through the estate pipeline (manifest-gated, rights
  recorded): the Apache-2.0 google/transit `trip-updates-full.asciipb` (the
  rights-unambiguous anchor) and a real MBTA `VehiclePositions.pb` snapshot
  (564 live vehicles; rights stated as the MassDOT license, whose exact
  commercial clause could **not** be machine-verified — the manifest says so and
  requires review before any promotion beyond Demonstrated).

## The gap this surfaced (the headline finding — a Program A follow-up)

GTFS-Realtime is keyed by `(trip, stop, vehicle)` and carries **no rider
request**, but every canonical entity — including `Outcome` — is
rider-request-keyed. Mapping therefore forces two compromises, both recorded:
(1) `Outcome.request_id` becomes a **synthetic placeholder referencing no
ServiceRequest**; (2) `Outcome` has **no operational-context fields** (no
stop_id, vehicle_id, route_id, position, occupancy), so almost everything a
GTFS-RT entity says becomes semantic loss.

**Finding: the canonical model lacks a first-class, request-independent
operational/telemetry entity** (a `VehicleTelemetry` / `StopTimeObservation`).
Until it has one, the single largest transit-integration surface in the world
can only be mapped by squinting at the rider-outcome record. This is a Program A
(canonical substrate) follow-up, flagged in `IMPLEMENTATION_STATUS.md`.

**TODS deferred (Specified, not built)** for the same reason: TODS describes
runs, blocks, pieces-of-work, and deadhead segments — almost none of which have
a canonical home today (no `Block`/`RunCut`/`PieceOfWork` entity). Half-building
it would route most of TODS to semantic loss. The honest move is to let the
gap-driven canonical work (an operational entity family) land first.

## Consequences

- 20 tests; both real samples map (MBTA → 251 observed-arrival Outcomes, 314
  in-transit quarantined; the asciipb → 3 prediction Outcomes). Status
  **Demonstrated** (open public real-time data, not consented operator data).
- `pyproject.toml` gained `gtfs-realtime-bindings==2.1.0` + `protobuf==6.33.5`
  (a genuine new capability's dependency); CI installs and collects cleanly.
- The MBTA rights caveat is documented; the Apache-2.0 sample is the anchor to
  rely on if a single rights-clean source is preferred.
