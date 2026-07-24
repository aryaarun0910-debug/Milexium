# ADR-0036: MinIO-backed estate raw zone (free object storage, no paid cloud)

- **Status:** Accepted
- **Date:** 2026-07-24
- **Packet:** MX-C-MINIO-ESTATE-002

## Context

ADR-0032 brought up the dev compose stack and wired the first content-addressed
object-storage path (`packages/estate/object_store.py` `MinioObjectStore`), but
the estate's raw zone still lived only on local disk — MinIO existed as an
additive backend nobody called. The founder's hard constraint stands: **no paid
cloud object storage** (AWS S3 / GCS / Azure) until a YC partner is onboard.
MinIO, however, is free and already running, so the natural next step (flagged in
ADR-0032's consequences) is to let it back the raw zone.

## Decision

`packages/estate/acquire.py` gains an **additive, default-OFF** object-store
backing. After a validated object is promoted to its raw zone, `acquire()`
optionally *also* mirrors it, content-addressed, into MinIO:

- Two new keyword args: `object_store=<MinioObjectStore|None>` (the seam tests
  inject a store directly) and `back_with_object_store=False` (auto-resolves the
  running MinIO from `infra/compose/.env` via `_resolve_object_store()`, which
  returns `None` — never raises — when the `minio` client, its credentials, or
  the container are absent).
- **Content-address invariant, enforced:** the key MinIO returns must equal the
  sha256 `acquire()` already computed for the raw object; a mismatch raises
  `AcquisitionError`. The estate's own content address and the object-store key
  are therefore *the same value* — dedup-safe, and tamper-evident on every read
  (the same integrity stance as the event-log hash chain).
- `object_store_key` / `object_store_bucket` are written into the catalog entry
  **only when a store was actually used**, so the no-store path emits a
  byte-for-byte identical catalog record. `AcquisitionResult` gains
  `object_store_key: str | None = None`; `CatalogEntry` / `inventory()` surface
  the key (reading it with `.get()` so older records without the field still
  load).

Local disk stays authoritative and the **default**; MinIO is a mirror, not a
replacement.

## Consequences

- **The estate raw zone is now Exists (dev), backed by MinIO.** A conformance
  test (`conformance/property-tests/test_estate_minio_backing.py`) drives a full
  `acquire()` with backing on (using the existing downloader-injection seam, so
  no network): the object lands in the raw zone **and** in MinIO under its
  sha256, the catalog records `object_store_key == sha256`, and `store.get(key)`
  round-trips the exact raw bytes. It **ran (not skipped)** against the live
  MinIO — 2 new tests pass; a companion test proves backing-OFF acquisition is
  unchanged and records no key. It **skips cleanly** (mirroring
  `test_object_store.py`) when `minio`/creds/container are absent, so CI and
  clean clones stay green. The 5 pre-existing governance tests
  (`test_estate_acquisition.py`) pass unchanged.
- **No paid-cloud SDK, no credentials.** Nothing from boto3/aws/gcs/azure was
  added; the only client is the existing optional `minio` (`objectstore` extra).
  `infra/compose/.env` remains gitignored.
- **Not built (Specified):** production per-tenant bucket isolation, lifecycle /
  retention policies, TLS on the dev endpoint, and promoting *existing* on-disk
  datasets into MinIO retroactively (only new acquisitions are mirrored). A
  production object store uses real cloud credentials and per-tenant isolation —
  deferred until a YC partner is onboard, per the founder's constraint.
