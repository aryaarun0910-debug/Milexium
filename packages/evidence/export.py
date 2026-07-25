"""Evidence-pack export + independent re-verification (Program I extension).

The strategic artifact: a self-contained, portable bundle for one decision that
a third party can verify WITHOUT Milexium's code trusting itself and WITHOUT a
live database connection -- the "machine-verifiable export" of blueprint 07.

An `EvidencePack` embeds the reconstructed `EvidencePacket`, the raw event rows
it was built from (so re-verification recomputes the hash chain from source
bytes, not a claim), the optional outcome, and a manifest carrying a bundle
checksum. `verify_evidence_pack` re-derives everything independently and reports
whether the pack still holds together.

Redaction (`redact_pack`) is deliberately a *separate* artifact with a weaker
guarantee: masking payload fields necessarily breaks hash-chain
re-verification of those events (the hash was computed over the original
payload), so a redacted pack is explicitly marked non-independently-verifiable.
Field masking here is for sharing convenience, NOT HIPAA de-identification
(blueprint 10) -- combinations of remaining fields can still re-identify, and
the pack says so.

A pack may also carry a **deadhead teardown** (ADR-0039) -- the specific,
checkable finding about a partner's own operation. It is carried the same way
everything else here is carried: with its inputs embedded, so
`verify_evidence_pack` RE-DERIVES its headline figures from the segments and the
manifest's declared inputs rather than re-reading the numbers it is checking.
See `packages/evidence/teardown_evidence.py`; nothing on this verification path
imports the generator.
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict

from packages.canonical.events import canonical_json
from packages.evidence.builder import build_evidence_packet
from packages.evidence.models import EvidencePacket
from packages.evidence.teardown_evidence import (
    TeardownEvidence,
    redact_teardown_evidence,
    rederive_teardown,
)
from packages.verify.hash_chain_verifier import verify_chain

PACK_VERSION = "0.1.0"


class PackManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pack_version: str
    tenant_id: str
    aggregate_id: str
    event_count: int
    integrity_verified_at_export: bool
    bundle_sha256: str
    independently_verifiable: bool
    redacted_fields: tuple[str, ...] = ()
    note: str

    # WHY defaults: a pack carrying no teardown is exactly the ADR-0017 pack,
    # byte-for-byte, so existing packs and their checksums are untouched.
    teardown_included: bool = False
    teardown_id: str | None = None
    teardown_data_provenance: str | None = None
    """"real_public" or "synthetic", carried up to the manifest so a reader
    sees at the top of the pack what the finding was computed from. There is no
    "operator" value (ADR-0039) and this manifest must never invent one."""
    teardown_segment_count: int | None = None


class EvidencePack(BaseModel):
    """A portable, JSON-serializable evidence bundle for one aggregate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest: PackManifest
    evidence: dict
    raw_events: tuple[dict, ...]
    outcome: dict | None
    teardown: TeardownEvidence | None = None
    """An optional ADR-0039 deadhead teardown, carried with the segments it was
    computed from so its figures can be recomputed rather than believed."""

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "EvidencePack":
        return cls.model_validate(json.loads(text))


def _bundle_hash(
    evidence: dict,
    raw_events: tuple[dict, ...],
    outcome: dict | None,
    teardown: dict | None = None,
) -> str:
    """Deterministic checksum over the pack's verifiable content (everything
    except the manifest, which carries this hash). Reuses canonical_json so an
    external re-implementation can reproduce it byte-for-byte.

    The teardown key is added only when a teardown is actually carried, so a
    pack without one hashes exactly as it did before teardowns existed -- an
    absent capability must not silently change an already-issued artifact's
    checksum.
    """
    payload = {"evidence": evidence, "raw_events": list(raw_events), "outcome": outcome}
    if teardown is not None:
        payload["teardown"] = teardown
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


_PACK_NOTE = (
    "Independently verifiable: verify_evidence_pack recomputes the hash "
    "chain from raw_events and re-checks the bundle checksum without "
    "trusting the exporter."
)

_PACK_TEARDOWN_NOTE = (
    " This pack also carries a modelled deadhead teardown (ADR-0039) and the "
    "trip-structure segments it was computed from: verify_evidence_pack "
    "RE-DERIVES its headline minute and money figures from those segments and "
    "the teardown manifest's declared inputs, so a recorded figure that does "
    "not follow from the data fails verification. The money figures are the "
    "accounting value of empty time at the operator's own rate, hedged and "
    "never a guaranteed or realised saving."
)


def build_evidence_pack(events, raw_rows, outcome=None, teardown=None) -> EvidencePack:
    """Build a fully independently-verifiable evidence pack for one aggregate.

    Filters `raw_rows` to the aggregate's own rows (so passing a whole tenant's
    rows is fine) and embeds them, so `verify_evidence_pack` can recompute the
    chain from the pack alone.

    `teardown` is an optional `TeardownEvidence` from
    `packages.evidence.teardown_capture.capture_teardown` -- already carrying
    its own segments, so this function embeds a finding that can be recomputed,
    not one that must be believed.
    """
    packet: EvidencePacket = build_evidence_packet(events, raw_rows, outcome=outcome)
    aggregate_id = packet.aggregate_id
    own_rows = tuple(row for row in raw_rows if row.get("aggregate_id") == aggregate_id)

    evidence = packet.model_dump(mode="json")
    outcome_dump = outcome.model_dump(mode="json") if outcome is not None else None
    teardown_dump = teardown.model_dump(mode="json") if teardown is not None else None
    bundle_sha256 = _bundle_hash(evidence, own_rows, outcome_dump, teardown_dump)

    manifest = PackManifest(
        pack_version=PACK_VERSION,
        tenant_id=str(packet.tenant_id),
        aggregate_id=aggregate_id,
        event_count=len(own_rows),
        integrity_verified_at_export=packet.integrity_verified,
        bundle_sha256=bundle_sha256,
        independently_verifiable=True,
        note=_PACK_NOTE if teardown is None else _PACK_NOTE + _PACK_TEARDOWN_NOTE,
        teardown_included=teardown is not None,
        teardown_id=None if teardown is None else teardown.teardown_id,
        teardown_data_provenance=None if teardown is None else teardown.data_provenance,
        teardown_segment_count=None if teardown is None else len(teardown.segments),
    )
    return EvidencePack(
        manifest=manifest,
        evidence=evidence,
        raw_events=own_rows,
        outcome=outcome_dump,
        teardown=teardown,
    )


class PackVerification(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reverified: bool
    bundle_hash_matches: bool
    chain_reverified: bool
    chain_violations: tuple[str, ...]
    reasons: tuple[str, ...]

    teardown_present: bool = False
    teardown_figures_rederived: bool | None = None
    """True when every checked headline figure was recomputed from the embedded
    segments and matched; False when one did not; None when no teardown is
    carried. Never True on the strength of the recorded numbers alone."""
    teardown_fingerprint_rederived: bool | None = None
    """None means "could not be checked, by declared design" (a redacted pack),
    which is deliberately distinct from False ("checked and wrong") and from
    True ("checked and right")."""
    teardown_mismatches: tuple[str, ...] = ()


class _TeardownCheck(BaseModel):
    """Internal: the teardown half of a pack verification, kept separate so
    "the figures do not re-derive" and "the manifest misdescribes what it
    carries" stay distinguishable instead of collapsing into one flag."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    figures_rederived: bool | None = None
    fingerprint_rederived: bool | None = None
    manifest_consistent: bool = True
    mismatches: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return (
            self.figures_rederived is not False
            and self.fingerprint_rederived is not False
            and self.manifest_consistent
        )


def _verify_teardown(pack: EvidencePack) -> _TeardownCheck:
    """Re-derive a carried teardown and cross-check the pack manifest's own
    description of it."""
    manifest = pack.manifest
    carried = pack.teardown
    if carried is None:
        if manifest.teardown_included:
            return _TeardownCheck(
                manifest_consistent=False,
                mismatches=("manifest claims a teardown is included, but the pack carries none",),
            )
        return _TeardownCheck()

    result = rederive_teardown(carried)

    # The pack manifest is a summary of the teardown it carries; a summary that
    # disagrees with the thing summarized is a failed verification, not a note.
    manifest_problems: list[str] = []
    if not manifest.teardown_included:
        manifest_problems.append("pack carries a teardown its manifest does not declare")
    if manifest.teardown_id != carried.teardown_id:
        manifest_problems.append(
            f"pack manifest teardown_id {manifest.teardown_id!r} does not match the "
            f"carried teardown's {carried.teardown_id!r}"
        )
    if manifest.teardown_data_provenance != carried.data_provenance:
        manifest_problems.append(
            f"pack manifest data provenance {manifest.teardown_data_provenance!r} does "
            f"not match the carried teardown's {carried.data_provenance!r}"
        )
    if manifest.teardown_segment_count != len(carried.segments):
        manifest_problems.append(
            f"pack manifest teardown_segment_count {manifest.teardown_segment_count!r} "
            f"does not match the {len(carried.segments)} segments carried"
        )

    return _TeardownCheck(
        figures_rederived=result.figures_rederived,
        fingerprint_rederived=result.fingerprint_rederived,
        manifest_consistent=not manifest_problems,
        mismatches=result.mismatches + tuple(manifest_problems),
        reasons=result.reasons,
    )


def verify_evidence_pack(pack: EvidencePack) -> PackVerification:
    """Independently re-verify a pack from its own bytes. A third party runs
    this to confirm the pack was not altered after export, that the embedded
    event chain still verifies, and that any carried teardown's headline figures
    actually follow from the data embedded with them -- none of these checks
    trusts a manifest claim, all recompute from source."""
    reasons: list[str] = []

    teardown_dump = pack.teardown.model_dump(mode="json") if pack.teardown is not None else None
    recomputed = _bundle_hash(pack.evidence, pack.raw_events, pack.outcome, teardown_dump)
    bundle_hash_matches = recomputed == pack.manifest.bundle_sha256
    if not bundle_hash_matches:
        reasons.append(
            f"bundle checksum mismatch: manifest says {pack.manifest.bundle_sha256}, "
            f"recomputed {recomputed} (pack content was altered after export)"
        )

    teardown = _verify_teardown(pack)
    if not teardown.passed:
        reasons.extend(f"teardown: {m}" for m in teardown.mismatches)
    if pack.teardown is not None and teardown.fingerprint_rederived is None:
        # A check that was skipped by design is reported, never left implicit.
        reasons.extend(f"teardown: {r}" for r in teardown.reasons)

    if not pack.manifest.independently_verifiable:
        reasons.append(
            "pack is marked non-independently-verifiable (redacted); chain "
            "re-verification is not possible on masked events by design"
        )
        return PackVerification(
            reverified=False,
            bundle_hash_matches=bundle_hash_matches,
            chain_reverified=False,
            chain_violations=(),
            reasons=tuple(reasons),
            teardown_present=pack.teardown is not None,
            teardown_figures_rederived=teardown.figures_rederived,
            teardown_fingerprint_rederived=teardown.fingerprint_rederived,
            teardown_mismatches=teardown.mismatches,
        )

    violations = verify_chain(list(pack.raw_events))
    chain_reverified = len(violations) == 0
    if not chain_reverified:
        reasons.extend(f"{v.kind} at seq {v.sequence}: {v.detail}" for v in violations)

    return PackVerification(
        reverified=bundle_hash_matches and chain_reverified and teardown.passed,
        bundle_hash_matches=bundle_hash_matches,
        chain_reverified=chain_reverified,
        chain_violations=tuple(f"{v.kind}:{v.detail}" for v in violations),
        reasons=tuple(reasons),
        teardown_present=pack.teardown is not None,
        teardown_figures_rederived=teardown.figures_rederived,
        teardown_fingerprint_rederived=teardown.fingerprint_rederived,
        teardown_mismatches=teardown.mismatches,
    )


_REDACTED_NOTE = (
    "REDACTED pack: named payload fields are masked, which breaks "
    "per-event hash-chain re-verification by design. This is field "
    "masking for sharing, NOT HIPAA de-identification -- remaining "
    "fields may still re-identify. The bundle checksum still detects "
    "tampering with the redacted pack as a whole."
)

_REDACTED_TEARDOWN_CLAUSE = (
    " The carried teardown's run identifiers are masked in both its ranking and "
    "its embedded segments, so no run leaves in this pack. Its minute and money "
    "figures REMAIN re-derivable and are still checked (they never depended on "
    "run identity); what is lost is the fingerprint binding these segments to "
    "the original teardown. verify_evidence_pack reports that as not-checked "
    "rather than as passed."
)


def redact_pack(pack: EvidencePack, sensitive_payload_keys: tuple[str, ...]) -> EvidencePack:
    """Return a shareable copy with the named payload keys masked in every
    embedded event, and every run identifier masked in a carried teardown.
    Explicitly marks the result non-independently-verifiable (masking breaks
    chain re-verification) and re-anchors the bundle checksum over the redacted
    content so the redacted pack is still tamper-evident as a whole -- just not
    chain-verifiable per event.

    Teardown run identifiers are masked unconditionally rather than on request:
    a run reference is the operator's own operational identifier, and the
    redacted pack is the copy that leaves the building. (Nothing rider-linked is
    masked because a segment structurally cannot carry anything rider-linked --
    see `packages/evidence/teardown_evidence.py`.)

    This is field masking for sharing, NOT HIPAA de-identification: remaining
    fields may still re-identify. The manifest note says so.
    """
    masked_events = []
    for row in pack.raw_events:
        new_row = dict(row)
        if "payload_json" in new_row:
            try:
                payload = json.loads(new_row["payload_json"])
            except (json.JSONDecodeError, TypeError):
                payload = {}
            for key in sensitive_payload_keys:
                if key in payload:
                    payload[key] = "[REDACTED]"
            new_row["payload_json"] = canonical_json(payload)
        masked_events.append(new_row)
    masked = tuple(masked_events)

    teardown = None if pack.teardown is None else redact_teardown_evidence(pack.teardown)
    teardown_dump = teardown.model_dump(mode="json") if teardown is not None else None
    redacted_fields = tuple(sensitive_payload_keys)
    note = _REDACTED_NOTE
    if teardown is not None:
        redacted_fields += ("teardown.top_runs[].run_ref", "teardown.segments[].run_ref")
        note += _REDACTED_TEARDOWN_CLAUSE

    bundle_sha256 = _bundle_hash(pack.evidence, masked, pack.outcome, teardown_dump)
    manifest = pack.manifest.model_copy(
        update={
            "bundle_sha256": bundle_sha256,
            "independently_verifiable": False,
            "redacted_fields": redacted_fields,
            "note": note,
        }
    )
    return pack.model_copy(
        update={"manifest": manifest, "raw_events": masked, "teardown": teardown}
    )
