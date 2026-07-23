# ADR-0017: Independently-verifiable evidence pack export (Program I extension)

- **Status:** Accepted
- **Date:** 2026-07-23

## Context

The go-to-market rests on "undeniable operational evidence" you can hand a
partner. `packages/evidence` builds an in-memory `EvidencePacket`, but there
was no portable artifact a third party could take away and verify *without*
Milexium's running system — the "machine-verifiable export" of blueprint 07.

## Decision

`packages/evidence/export.py` adds a portable `EvidencePack`:

- **`build_evidence_pack(events, raw_rows, outcome=None)`** — embeds the
  reconstructed `EvidencePacket`, the aggregate's own raw event rows, the
  outcome, and a manifest with a bundle sha256. JSON-serializable
  (`to_json`/`from_json`).
- **`verify_evidence_pack(pack)`** — re-derives everything from the pack's own
  bytes: recomputes the bundle checksum (detects any post-export alteration)
  and re-runs `verify_chain` over the embedded raw events (detects a broken
  hash chain). Neither check trusts the manifest's claims — both recompute
  from source. A third party runs this to confirm the pack independently.
- The bundle hash uses `canonical_json` (the same normative serializer as the
  event log) so an external re-implementation can reproduce it byte-for-byte.

### The redaction tradeoff, made explicit

`redact_pack(pack, sensitive_payload_keys)` masks named payload fields for
sharing. Masking a payload **necessarily breaks per-event hash-chain
re-verification** (the hash was computed over the original payload), so a
redacted pack is explicitly marked `independently_verifiable=False`, and
`verify_evidence_pack` reports that honestly rather than pretending it still
chain-verifies. The redacted pack keeps a bundle checksum (so tampering with
the redacted pack *as a whole* is still detectable), but per-event chain proof
is gone by construction.

The manifest note states plainly: this is **field masking for sharing, NOT
HIPAA de-identification** (blueprint 10) — remaining fields can still
re-identify. Two distinct artifacts with two distinct guarantees, never
conflated.

## Consequences

- The full (unredacted) pack is the strong artifact: fully independently
  re-verifiable, portable JSON, no live system needed. This is the one to hand
  a technical partner or auditor.
- Conformance proves the honest properties: a round-trip re-verifies; altering
  content is caught by the bundle checksum; even an attacker who re-anchors the
  bundle checksum after tampering is still caught by the inner hash chain; a
  redacted pack masks the field and refuses to claim chain-verifiability.
- Consistent with `blueprint/01`: the pack is tamper-evident, not "immutable"
  and not a compliance certificate — the code and notes say exactly that.
- Not built (Specified): selective-disclosure via per-field commitments (a
  Merkle/salted-hash scheme that would let a field be redacted while still
  proving its original commitment), signed checkpoints in a separate trust
  boundary, and non-JSON compact export formats.
