# ADR-0011: TLC FHVHV adapter design decisions (second Connect adapter)

- **Status:** Accepted
- **Date:** 2026-07-23

## Context

`app/connect/reference_agency_trips.py` (ADR-0007) is the only adapter
against the `SourceAdapter` contract so far, and its source is explicitly
fictional. Proving `blueprint/01-north-star-and-boundaries.md`'s "unavoidable"
test #1 ("external data producers map to the Milexium schema... without
custom downstream code for every model") needs a second, structurally
different, **real** source. NYC TLC FHVHV trip records
(`realdata/raw_tlc/*.parquet`, already downloaded in this repo for the
forecasting pipeline) are real individual trips — not fictional, but also not
consented paratransit operator data.

## Decision

`app/connect/tlc_trips.py`'s `TlcTripsAdapter` makes several real
mapping judgment calls, recorded here rather than left implicit in code
comments alone:

1. **`request_datetime` → `requested_at`** (not `pickup_datetime`) — FHVHV
   has a genuine request-instant field, a cleaner fit than the reference
   adapter had. Still naive local time treated as UTC directly (no offset
   conversion), the same simplification used elsewhere in this repo — flagged
   as a real ~4-5 hour (EDT/EST) discrepancy from true UTC, not silently
   accurate.
2. **`pickup_datetime` → `actual_pickup_at`**, `status` left at `REQUESTED`
   — mapping the observed pickup to `ServiceRequestState.COMPLETED` would
   require walking the aggregate through `NEGOTIATED`/`SCHEDULED`/
   `IN_PROGRESS` via `check_transition`, out of scope for a one-row parse.
   Recorded as a `dropped` semantic-loss entry so the mismatch is explicit,
   not silently implied by an unset field.
3. **`wav_request_flag` → `mobility_device`, a deviation from the original
   task brief.** The task assumed TLC carries no mobility-device signal;
   direct inspection of the real file found `wav_request_flag` (wheelchair-
   **accessible-vehicle** request — 4,238 of 20,159,102 rows in the 2019-02
   file are `Y`). Mapped `Y` → `"wheelchair"` with an explicit caveat in the
   semantic-loss reason that this is a vehicle-accessibility request, not a
   direct statement of the rider's own mobility device — the two are related
   but not identical concepts. `dropped` disposition is reserved for the
   genuinely-null case.
4. **`rider_ref` is a synthetic, non-stable, non-joinable per-row
   placeholder** (`tlc-no-rider-<sha256 of request_datetime|PULocationID|
   DOLocationID|driver_pay>`), not a tokenized real identifier. FHVHV
   publishes no rider/passenger identifier of any kind, by design, for rider
   privacy — the only identifiers present (`hvfhs_license_num`,
   `dispatching_base_num`, `originating_base_num`) name the TNC and
   dispatching base, not a person. Tokenizing one of those the way the
   reference adapter tokenizes an actual per-rider id would misrepresent
   millions of unrelated riders sharing one TNC/base as a single identity —
   a real privacy/correctness error, not just an inconvenience. A `dropped`
   semantic-loss entry always records that no rider-identity concept exists
   in this source.
5. **TLC's own placeholder zone codes (264 = unknown, 265 = outside NYC)
   quarantine rather than pass through as string zones** — 1,292 pickups and
   601,365 dropoffs (of 20,159,102 rows in one file) carry one of these,
   a real and common failure mode, not a hypothetical edge case.
6. Schema drift is real, not hypothetical: `fhvhv_tripdata_2026-05.parquet`
   has a 25th column, `cbd_congestion_fee` (NYC's 2025+ congestion-pricing
   program), absent from `fhvhv_tripdata_2019-02.parquet`. It surfaces as an
   `unmapped_extension` semantic-loss entry, proving the adapter degrades
   gracefully to schema drift rather than breaking.

## Consequences

- Status label for everything built here is **Demonstrated**, not
  **Validated** — TLC is real public data, but neither paratransit-specific
  nor consented-operator data; it does not upgrade the status tier, per
  `knowledge/architecture/decisions/0001`.
- Two adapters against one contract, mapping structurally different real and
  fictional sources (delimited CSV with string/empty-string conventions vs.
  columnar Parquet with pandas/numpy-typed nulls) onto the same
  `ServiceRequest`, is now real evidence toward blueprint 01's "unavoidable"
  test #1 — not yet a completed proof (a third source, ideally consented
  operator data, would strengthen it further).
- Decision #3 (WAV flag) is the one most likely to warrant a second opinion
  if this adapter is ever used for anything beyond a schema-heterogeneity
  demonstration — flagged explicitly rather than buried in code.
