# third_party/

Provenance, license, and patch records for every vendored or pinned external
dependency, per the expansion plan's non-negotiable: "Every external dependency
must be pinned by version and commit with license, SBOM, upstream provenance,
and local patch records."

Nothing is vendored here yet. Per `blueprint/01-north-star-and-boundaries.md` and
the dossier coverage rules in `blueprint/20-dossier-coverage-ledger.md`, upstream
projects (TurboVec, DiskANN, OpenEnv, etc.) are not vendored blindly — each
requires an ADR recording the maturity, license, and security review before
code lands here. See `workstreams/DOSSIER_COVERAGE.md` for the current status
of every candidate technology.

**Owner:** whoever proposes the vendoring ADR; the integration workstream must
approve before code lands.

**Test command:** `py -3 tools/audit_repository.py` includes a check that
nothing under `third_party/` lacks a license/provenance record (to be added
when the first dependency is vendored).
