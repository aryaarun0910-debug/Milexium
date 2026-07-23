# ADR-0013: Governed data estate with manifest-gated acquisition

- **Status:** Accepted
- **Date:** 2026-07-23

## Context

The strategic direction (2026-07-23) is to reposition Milexium as a transport
decision *runtime that other software companies integrate*, and to generate
undeniable operational evidence independently from public data rather than
waiting on a large agency. Both depend on data: the runtime needs a broad,
rights-clean, standards-covering estate, and independent evidence needs real
public data pulled at scale.

`blueprint/17-data-and-storage-readiness.md` specifies a 250 GB estate but is
emphatic that this is **not** a bulk download: "No download enters the estate
without [a manifest: rights, checksum, purpose, quality tests, retention]" and
"the system reports free-space ... before executing large transforms." The
value of the estate to an integrator is precisely that it is governed — every
byte's provenance, rights, and integrity are known.

## Decision

Build the estate's governance layer before pulling volume:

1. **`data/` zone layout** exactly per blueprint 17 (`catalog/`, `raw/public`,
   `raw/partner`, `quarantine/`, `canonical/`, `features/`, `networks/`,
   `standards/`, `simulation/`, `semantic/`, `experience/`, `benchmarks/`,
   `evidence/`, `scratch/`). Raw/derived zones are gitignored (large,
   reproducible); `catalog/` is committed (the governance ledger).
2. **`packages/estate/`**: an `AcquisitionManifest` contract mirroring
   blueprint 17's manifest fields (rights **must** be declared, not "unknown"),
   an `acquire()` that enforces the sequence *free-space check → quarantine
   download → checksum → promote to content-addressed name → catalog record*,
   and a `catalog` module that inventories retained bytes and reports disk
   headroom before any large transform.
3. **Prove it on real data before scaling**: acquired two rights-clean,
   on-point datasets end-to-end through the pipeline — a TIDES
   `trips_performed.csv` sample (Apache-2.0; the demand-responsive-transport
   trip-level standard, maximally on-brand for paratransit) into `standards/`,
   and a Geofabrik DC OSM extract (ODbL; 20.9 MB real routing data) into
   `networks/`.
4. **Do not bulk-download the 250 GB or the 152 dossier technologies now.**
   Each future dataset is a queued manifest (declared + rights-checked, one
   `acquire()` call away); each technology is gated by
   `third_party/VENDORING_PROCESS.md` (review manifest + ADR, no blind clone).

## Consequences

- The estate is **governed from byte one**: a manifest without declared rights
  is unacquirable; a checksum mismatch leaves the object in quarantine, never
  the trusted zone; free space is reported before every acquisition. Five
  conformance tests enforce this (`conformance/property-tests/test_estate_
  acquisition.py`).
- "Download everything" is reframed, not refused: every intended dataset gets
  a manifest (so the intent is recorded and rights-checked), and acquisition
  is one command per dataset — scalable deliberately, not a single reckless
  bulk pull that could fill the disk or ingest unlicensed data.
- The pre-existing ~60 GB `realdata/`/`ntd/` corpus is **not** relocated
  (`docs/DATA_STORAGE.md`'s corruption/path-risk argument stands); a future
  catalog back-fill can register those objects in place.
- Standards data (`data/standards/`) doubles as the adapter-certification
  corpus for Program B — the next high-leverage build (GTFS/Flex/TIDES
  adapters) is what makes Milexium a runtime others integrate, and it now has
  a real, rights-clean source to build against.
- PostGIS is still not installed; `networks/` OSM data has no routing-graph
  derivation yet (that's Program F/H). The estate holds the raw input; the
  derived artifacts remain Specified.
