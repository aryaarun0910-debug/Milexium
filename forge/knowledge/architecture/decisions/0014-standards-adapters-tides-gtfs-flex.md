# ADR-0014: Standards adapters — TIDES and GTFS-Flex → ServiceRequest

- **Status:** Accepted
- **Date:** 2026-07-23

## Context

The strategic direction is a vendor-neutral transport decision runtime other
software integrates. Two open transport *standards* — TIDES (Transit ITS Data
Exchange Specification, demand-responsive/paratransit trip-level data) and
GTFS-Flex (the demand-responsive-transport feed standard) — are the most
on-brand ingestion targets for paratransit. Both now have adapters against the
`SourceAdapter` contract (ADR-0007), built against real rights-clean data
acquired through the estate pipeline (ADR-0013): a TIDES `trips_performed`
schema in `data/acquired/standards/` and a real GTFS-Flex on-demand feed (City of
Aspen "Downtowner"). This makes **five** adapters total (reference-agency CSV,
TLC Parquet, TIDES, GTFS-Flex) against one contract — real evidence toward
blueprint 01's "unavoidable" test #1.

## Decisions

### TIDES (`themis/connect/tides_trips.py`)

- **`requested_at` ← `service_date` at midnight UTC**, not `schedule_trip_start`.
  TIDES `trips_performed` is a *performed-trip* record with no rider
  request/booking timestamp. Reusing `schedule_trip_start` would falsely
  assert zero advance-notice booking (wrong for the advance-reservation DRT
  domain) and collapse two distinct fields. `service_date` at midnight is an
  obviously-synthetic day-granularity anchor that self-documents as "request
  instant unknown," preserves the natural `requested_at ≤ scheduled_pickup_at
  ≤ actual_pickup_at` ordering, and is always populated. Recorded as a
  `coerced` semantic-loss entry on every mapping. Trade-off (loss of
  request-time-of-day) is documented in the loss reason — this is the
  judgment most worth a second opinion.

### GTFS-Flex (`themis/connect/gtfs_flex.py`)

- **Unit of mapping**: one Flex `stop_times` row (joined to its `booking_rule`,
  `calendar` service dates, and `feed_info`) = one `ServiceRequest`
  representing a **bookable service window**, not a performed trip. A Flex feed
  describes *bookable service*, not individual rides.
- **The standout — negotiated windows**: `start_pickup_drop_off_window` /
  `end_pickup_drop_off_window` map directly onto `RequestTimes.
  negotiated_window_start` / `negotiated_window_end`. GTFS-Flex's booking
  window **is** the paratransit negotiated-window concept — the first
  ServiceRequest field for it any adapter here has been able to populate from
  real data (reference-agency and TLC both correctly left it unset). Daily
  time-of-day windows are anchored to `calendar.start_date` (fallback
  `feed_info.feed_start_date`); GTFS >24:00:00 times roll to the next day;
  naive local time treated as UTC — all recorded as `coerced` loss.
- **Service-template vs. actual-request**: `status=REQUESTED`, but a `coerced`
  loss entry records on every mapping that no rider/booking/demand event
  underlies it — this is service *availability*, not observed demand, and
  downstream consumers must not count it as demand. This is the key genuine
  distinction from the reference-agency/TLC rows (real, if anonymous,
  individual trips).
- A Flex window with no resolvable booking rule is quarantined (treated as out
  of scope) — the judgment most likely to warrant a second opinion.

### Common to both

- No rider identity in either source → synthetic non-joinable `rider_ref`
  (same pattern as `tlc_trips.py`), recorded as loss.
- Every source field with no `ServiceRequest` v0.1 home (TIDES route/vehicle/
  block/shape; Flex booking_type/prior_notice/phone/messages) → `dropped`
  loss, never silently discarded.
- Status: **Demonstrated** — both are open-spec fixtures/example feeds, not
  consented operator data. Never "Validated."

## Consequences

- Central wiring: all adapters (including the previously-unwired `TlcTripsAdapter`)
  are now exported from `themis/connect/__init__.py`.
- GTFS-Flex proving the negotiated-window mapping from real data is a concrete
  signal that the canonical `RequestTimes` contract actually fits the
  demand-responsive-transport domain it was designed for — not just the
  fictional reference agency.
- Neither adapter yet handles the *full* standard (TIDES has ~10 other tables;
  GTFS-Flex has location groups, geojson service areas, continuous stops) —
  those remain Specified. This is the trip/booking slice, the part that maps
  to `ServiceRequest`.
