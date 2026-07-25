# ADR-0045: `redact_pack` now actually redacts

- **Status:** Accepted
- **Date:** 2026-07-25
- **Packet:** MX-I-REDACTION-FIX-005
- **Fixes:** the defect recorded in ADR-0044

## Context

ADR-0044 recorded a confirmed defect: **`redact_pack` did not redact.** It masked
the named sensitive payload keys in `pack.raw_events[].payload_json` but left the
same values in `pack.evidence` — the `EvidencePacket` dump, which embeds event
payloads. The masking path never referenced `pack.evidence` at all.

`redact_pack` exists to produce the **shareable** pack — the redacted
procurement/evidence bundle of ADR-0017/0020, the artifact you hand a third
party. It was returning a pack that still carried what it claimed to have
removed, and the failure was silent: the caller sees "redacted" and passes it on.

## Decision

**Masking follows the data, not a list of places.** `_mask_named_keys` walks
dicts and lists at any depth and is applied to `raw_events[].payload_json`,
`evidence`, and `outcome`. The previous raw_events behaviour and the
`[REDACTED]` marker are preserved (now the named constant `REDACTED_MARKER`,
with the same "`None` is not a mask" discipline as `REDACTED_RUN_REF`). The
original bug was a masking routine that enumerated *locations*; enumerating
locations fails the moment the IR grows one.

**The bundle checksum is anchored over the masked content.** It previously
hashed `pack.evidence` unmasked, so a redacted pack was tamper-evident over
something it did not carry.

**Verification re-derives the redaction claim rather than believing it.**
`PackVerification` gained `masking_complete` and `unmasked_paths`, recomputed by
walking the pack for the keys `manifest.redacted_fields` names. `None` = not
checked, `True` = checked clean, `False` = a value survives. **A pack that
*claims* a redaction it did not perform now fails `reverified`** even when the
hash chain and bundle checks pass — which is exactly the shape of the bug being
fixed, so the class of defect is now caught rather than just this instance.

**What cannot be masked is stated in the artifact**, not swallowed: a
post-redaction scan reports surviving values in `manifest.note`, naming
*locations and never the value* — the analogue of the teardown's `None`
fingerprint with a stated reason.

## Consequences

- **11 tests**, and the deliverable is a real leak test: a distinctive sensitive
  value is asserted **absent from `redacted.model_dump_json()` and
  `redacted.to_json()`** — the raw serialized text a partner is handed, not a
  parsed subset.
- **The tests are proven to bite:** with `export.py` reverted to the previous
  commit, **8 of the 11 fail**, including the leak test.
- `packages/evidence/models.py` was **not** touched — masking is shape-agnostic,
  so the IR never had to move.
- `contracts/` verified byte-identical after regeneration.

**A constraint worth recording, because it shaped the design:** the fix could not
add a field to `PackManifest`. `PackManifest` is exported into
`contracts/openapi/milexium-api-v0.1.json`, and CI runs a `git diff --exit-code`
drift check over `contracts/`, which the packet did not own. Consequence
reporting therefore rides on the existing free-text `note`. `PackVerification`
appears in no contract artifact, so the two new fields there are safe. This is
the contract layer doing its job — making a schema change visible and deliberate
rather than incidental.

**Honest limitations:**

- **Key-based masking cannot reach a value copied into free text** — an
  identifier that happens to equal it, or a `jsonschema` message in
  `schema_violations` quoting the offending instance. This is now *detected and
  reported with locations*, but not removed: scrubbing substrings out of recorded
  strings would corrupt the record rather than redact it. A test covers exactly
  this case.
- **The scan compares string values only.** A masked number or boolean is
  indistinguishable from a sequence number or a `true`, so it is masked but not
  scanned for.
- **Masking is literal about key names** — naming a key that also exists as a
  structural field masks it there too.
- Verification can re-derive that the *named keys* are masked everywhere; it
  cannot check the free-text residue (it does not know the original values) and
  deliberately does not restate the producer's scan result as if it had checked.
- Unchanged from ADR-0017: a redacted pack still cannot chain-reverify per event;
  selective disclosure via per-field commitments remains Specified-not-built.
  **Redaction is field masking for sharing, not de-identification.**
