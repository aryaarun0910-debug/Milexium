# ADR-0020: Period, incident, and procurement evidence bundles (Program I)

- **Status:** Accepted
- **Date:** 2026-07-24

## Context

The single-decision `EvidencePack` (ADR-0017) covers one aggregate. A partner or
procurement reviewer needs evidence spanning a *period* or centered on an
*incident*, plus a procurement scaffold — `blueprint/07` ("decision, incident,
period, and procurement evidence packs") and the `blueprint/10` procurement
list.

## Decision

`aletheia/evidence/packs.py`:

- **`PeriodEvidencePack`** / `build_period_pack` / `verify_period_pack` —
  bundles each aggregate's single-aggregate `EvidencePack` (reuse, not
  reimplementation) over a window, plus a `PeriodRollup` of **counts**
  (decisions/overrides/denials/outcomes — tallies, explicitly not causal
  claims) and the actual covered range.
- **`IncidentEvidencePack`** / `build_incident_pack` / `verify_incident_pack` —
  primary (disputed) aggregate(s) + related context, each embedding the reused
  `EvidencePacket` so the known/proposed/verified/overridden/observed narrative
  survives verbatim.
- **`ProcurementBundle`** / `build_procurement_bundle` — a machine-readable
  scaffold of the 13 `blueprint/10` items with three honest statuses
  (`available` / `partial` / `not_yet_available`) and a `requires_external_input`
  flag. Available items carry real repo references; encryption/subprocessor/
  certifications are empty placeholders flagged for legal/ops input. A test
  asserts no item claims "compliant"; the disclaimer states "NO compliance
  claim."

Every bundle splits into a nested `body` (the verifiable content) + a `manifest`
(`bundle_sha256` over `canonical_json(body)` — same normative serializer as the
ledger). Verification never trusts the manifest: it recomputes the outer
checksum, calls the existing `verify_evidence_pack` on **every** embedded pack
(each inner hash chain re-verifies from its own raw rows), and for periods
re-tallies the rollup and re-derives the coverage range.
`independently_verifiable` propagates as `all(embedded.independently_verifiable)`
— embedding a redacted pack honestly makes the whole bundle non-verifiable.

## Consequences

- Layered tamper-evidence: a tampered embedded event breaks the outer checksum;
  a re-anchored checksum is still caught by the embedded pack's own chain; a
  lying rollup re-anchored to a fresh checksum is caught by the re-tally (all
  tested).
- Cross-tenant bundles are refused at build time (a privacy boundary), as are
  empty period/primary sets.
- The procurement bundle carries no ledger/verification machinery — it is a
  static, honest current-state assessment (Demonstrated), not a verifiable
  artifact.
- Not built (Specified): bundle-level redaction (redact individual packs before
  composing), signed checkpoints in a separate trust boundary.
