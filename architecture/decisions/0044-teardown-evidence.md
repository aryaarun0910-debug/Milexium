# ADR-0044: Teardown evidence — verification that re-derives rather than re-reads

- **Status:** Accepted
- **Date:** 2026-07-25
- **Packet:** MX-I-TEARDOWN-EVIDENCE-004

## Context

The deadhead teardown (ADR-0039) produces exactly the artifact a design partner
should be handed: a specific, checkable finding about their own operation. It was
built to be verifiable — deterministic `teardown_id`, order-independent
`segment_sha256`, every input as `(name, value, source)`, numbered method steps —
and nothing verified it. Program I's evidence packs did not know it existed.

## Decision

An evidence pack can carry a teardown, and `verify_evidence_pack`
**independently re-derives** its headline figures rather than re-reading them.

`rederive_teardown` reads exactly two things: the **embedded segments** and the
manifest's **declared input records**. It re-implements the manifest's own
numbered method steps — re-splitting every segment at hour boundaries, regrouping
and re-ranking runs, parsing the declared rate and split out of the input records,
recomputing `deadhead_hours`, `value_at_full_cost` and the envelope, and
recomputing `segment_sha256` with its own implementation of the documented
order-independent fingerprint — and only then compares to the claim.

**Three things make it non-circular, and each is enforced rather than asserted:**

1. **Direction.** `TeardownFigures` deliberately carries *no input value* — every
   input lives in the manifest — so derivation runs inputs → figures and a claim
   can never be an input to its own check.
2. **Isolation.** `teardown_evidence.py` imports nothing from `packages.replay`,
   asserted against the module's **AST**, not its prose. `capture_teardown` is
   the single module allowed that import, and `export.py` is asserted clean too.
3. **Proof of direction.** A test alters *only* the declared rate in the manifest
   and leaves the money figure untouched. **A verifier that re-read the number
   would pass; this one fails.**

## Consequences

**26 tests.** The tamper test triples `value_at_full_cost` **and re-anchors the
bundle checksum**, so the outer hash is satisfied — the attacker wins the
checksum and re-derivation still catches it (`bundle_hash_matches: True`,
`teardown_figures_rederived: False` naming the field, `reverified: False`). Also
caught: doubled empty minutes; a minute moved between hour buckets with the total
preserved; a flattering segment subset swapped in; an envelope claimed with no
declared split; a manifest misdescribing its own provenance; and a tampered
figure inside an already-redacted pack — so redaction is not a laundering path.

**Redaction is honest about what it costs.** Run identifiers are masked
unconditionally in both the ranking and the embedded segments; a run that was
*never* identified stays `None`, because `None` is a fact about the source, not a
mask. The redacted pack **stays figure-verifiable** — minutes and money never
depended on run identity — while `teardown_fingerprint_rederived` becomes `None`,
not `True` and not `False`, with the reason stated in the artifact.

The framing constants (`FIXED_COST_HEDGE`, `DEADHEAD_TEARDOWN_NOTE`,
`MODELLED_COMPARISON_NOTE`) are carried **verbatim**, and capture *refuses* a
teardown whose framing was restated. `is_guaranteed_saving`/`causal_proof` raise
on the pack models; `data_provenance` is validated at the pack boundary and
`"operator"` is rejected.

## A pre-existing privacy defect this packet found, and did not fix

**`redact_pack` does not redact.** It masks the named payload keys in
`pack.raw_events` but leaves the same values in `pack.evidence` (the
`EvidencePacket` dump), which embeds event payloads. Verified directly:
`redact_pack` never references `pack.evidence` on the masking path.

So a pack produced specifically to be **shareable** — the procurement/redacted
bundle of ADR-0017/0020 — still carries the sensitive payload it claims to have
removed. This is a function failing at the one thing it exists to do, and the
failure mode is silent: the caller sees a "redacted" pack and hands it on.

It is **pre-existing, unrelated to teardowns, and outside this packet's scope**,
so it was not fixed here. The packet's redaction test **omits that assertion
rather than passing over it**, which is the right call — a green test asserting
around a known leak is worse than no test. It is now the top Program I follow-up.

## Other honest limitations

- **`teardown_id` is not recomputed**, only carried and covered by the bundle
  checksum. Reproducing it would mean copying the generator's private id-payload
  shape — exactly the coupling this packet exists to avoid. The re-derived
  data↔figure binding is `segment_sha256`.
- **Tolerance** is 1e-6 absolute + 1e-9 relative (figures are emitted rounded to
  6dp); a change below that is invisible to re-derivation, though the bundle
  checksum still catches any byte change.
- **Cost inputs are parsed from human-readable manifest records.** An unparseable
  record is reported as a mismatch, never defaulted, but the parser is coupled to
  that recorded format.
- **A redacted pack proves its figures follow from the segments it carries, not
  that those are the segments the teardown ran on.** Preserving that binding
  needs per-field commitments, already listed as not built in ADR-0017.
