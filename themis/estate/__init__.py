"""Data estate governance (Program C data-estate layer, blueprint 17).

Turns "we have some files" into "we have a governed estate": every retained
byte carries an acquisition manifest (owner, rights, checksum, purpose,
quality tests, retention), lands in a content-addressed raw zone only after
passing validation in quarantine, and is inventoried by a catalog that can
report free space before any large transform. This is the infrastructure the
repositioning depends on -- a rights-clean, reproducible, inventoried estate
is what makes Milexium a runtime other software companies can trust and
integrate, not an ungoverned pile of downloads.

v0.1 slice: manifest contract, single-file acquisition with free-space guard
+ quarantine + checksum, and catalog inventory/free-space reporting. Not yet
built (Specified): incremental/streaming acquisition, automatic scratch
expiry, dedup across logical datasets, and the canonical/feature/simulation
zone transforms.
"""

from themis.estate.manifest import (
    AcquisitionManifest,
    ManifestError,
    load_manifest,
)
from themis.estate.acquire import (
    AcquisitionError,
    FreeSpaceError,
    acquire,
)
from themis.estate.catalog import CatalogEntry, inventory, free_space_report
from themis.estate.object_store import (
    MinioObjectStore,
    ObjectStoreConfig,
    ObjectStoreError,
    minio_available,
)

__all__ = [
    "AcquisitionManifest",
    "ManifestError",
    "load_manifest",
    "AcquisitionError",
    "FreeSpaceError",
    "acquire",
    "CatalogEntry",
    "inventory",
    "free_space_report",
    "MinioObjectStore",
    "ObjectStoreConfig",
    "ObjectStoreError",
    "minio_available",
]

CONTRACT_VERSION = "0.1.0"
