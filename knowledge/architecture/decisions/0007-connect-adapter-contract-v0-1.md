# ADR-0007: Connect adapter contract v0.1 (AdapterResult, quarantine, semantic loss)

- **Status:** Accepted
- **Date:** 2026-07-23

## Context

`blueprint/03-connect-and-standards.md` specifies a full adapter surface
(inspect/validate_raw/map/reconcile/incremental_cursor/export) and requires
that imports report accepted/rejected/defaulted/quarantined counts plus
semantic-loss warnings rather than silently dropping data. Building the full
surface before any adapter exists to use it would be exactly the
"infrastructure before demand" risk `blueprint/15-risks-and-falsification.md`
warns against.

## Decision

Ship only the minimum adapter contract needed for one real adapter, in
`app/connect/adapter.py`:

- `AdapterResult[CanonicalT]` — a frozen, generic Pydantic model holding
  exactly one of `record` or `quarantine` (enforced by a model validator, not
  by convention), plus a tuple of `SemanticLossRecord`s.
- `QuarantinedRow` — preserves the raw row verbatim plus a reason, so a
  quarantined row can be inspected and re-run, never just discarded.
- `SemanticLossRecord` — one source field that didn't map cleanly, with a
  `disposition` constrained to `dropped|truncated|coerced|unmapped_extension`.
- `SourceAdapter` — a one-method `Protocol` (`parse(raw_row: dict) ->
  AdapterResult`). The rest of blueprint/03's adapter surface (validate_raw,
  reconcile, incremental_cursor, export, schema inference) remains
  **Specified**, not Exists, until a second adapter's needs justify it.
- `parse_batch()` catches any exception from a single row's `parse()` and
  turns it into a quarantine, so one bad row (or one adapter bug) cannot take
  down an entire import batch.

The first (and so far only) concrete adapter,
`app/connect/reference_agency_trips.py`'s `ReferenceAgencyTripsAdapter`,
maps `business/reference_agency/output/trips.csv` (an explicitly fictional source,
per `knowledge/docs/README.md`) onto `app.canonical.entities.ServiceRequest`. Two
interpretive calls this adapter made, worth recording since they're
judgment, not derivation from the contract:

1. The source records exactly one timestamp per trip (`date`+`hour`+
   `req_minute`) with no distinction between request time and negotiated/
   scheduled pickup time. The adapter maps it to `requested_at` only, leaves
   `negotiated_window_*`/`scheduled_pickup_at` unset, and records this as a
   `coerced` semantic-loss entry on every successful mapping rather than
   guessing a window.
2. The source has no timezone concept at all; the adapter treats every naive
   timestamp as UTC directly (same simplification `evidence/conformance/fixtures/
   builders.py` already uses elsewhere in this repo). A real external source
   would need a declared IANA zone per blueprint/03's mapping rules.

Rider identity is tokenized via `sha256(rider_id)[:24]` before it ever
touches a `ServiceRequest.rider_ref` — never the raw source id.

## Consequences

- Every claim about this adapter is **Demonstrated**, never **Validated**:
  the source is fictional generator output, not a consented operator export.
- A second, real adapter (e.g. an NTD or GTFS-Flex source) will very likely
  need at least `validate_raw` and `incremental_cursor` from the full
  blueprint/03 surface; add them then, against a real second use case, rather
  than speculatively now.
- `app/connect` is not yet wired into `app/README.md`'s package
  table or `pyproject.toml`; both are updated in this same integration pass.
