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
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict

from packages.canonical.events import canonical_json
from packages.evidence.builder import build_evidence_packet
from packages.evidence.models import EvidencePacket
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


class EvidencePack(BaseModel):
    """A portable, JSON-serializable evidence bundle for one aggregate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest: PackManifest
    evidence: dict
    raw_events: tuple[dict, ...]
    outcome: dict | None

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "EvidencePack":
        return cls.model_validate(json.loads(text))


def _bundle_hash(evidence: dict, raw_events: tuple[dict, ...], outcome: dict | None) -> str:
    """Deterministic checksum over the pack's verifiable content (everything
    except the manifest, which carries this hash). Reuses canonical_json so an
    external re-implementation can reproduce it byte-for-byte."""
    payload = {"evidence": evidence, "raw_events": list(raw_events), "outcome": outcome}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def build_evidence_pack(events, raw_rows, outcome=None) -> EvidencePack:
    """Build a fully independently-verifiable evidence pack for one aggregate.

    Filters `raw_rows` to the aggregate's own rows (so passing a whole tenant's
    rows is fine) and embeds them, so `verify_evidence_pack` can recompute the
    chain from the pack alone.
    """
    packet: EvidencePacket = build_evidence_packet(events, raw_rows, outcome=outcome)
    aggregate_id = packet.aggregate_id
    own_rows = tuple(row for row in raw_rows if row.get("aggregate_id") == aggregate_id)

    evidence = packet.model_dump(mode="json")
    outcome_dump = outcome.model_dump(mode="json") if outcome is not None else None
    bundle_sha256 = _bundle_hash(evidence, own_rows, outcome_dump)

    manifest = PackManifest(
        pack_version=PACK_VERSION,
        tenant_id=str(packet.tenant_id),
        aggregate_id=aggregate_id,
        event_count=len(own_rows),
        integrity_verified_at_export=packet.integrity_verified,
        bundle_sha256=bundle_sha256,
        independently_verifiable=True,
        note=(
            "Independently verifiable: verify_evidence_pack recomputes the hash "
            "chain from raw_events and re-checks the bundle checksum without "
            "trusting the exporter."
        ),
    )
    return EvidencePack(
        manifest=manifest, evidence=evidence, raw_events=own_rows, outcome=outcome_dump
    )


class PackVerification(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reverified: bool
    bundle_hash_matches: bool
    chain_reverified: bool
    chain_violations: tuple[str, ...]
    reasons: tuple[str, ...]


def verify_evidence_pack(pack: EvidencePack) -> PackVerification:
    """Independently re-verify a pack from its own bytes. A third party runs
    this to confirm the pack was not altered after export and that the embedded
    event chain still verifies -- neither check trusts the manifest's own
    claims, both recompute from source."""
    reasons: list[str] = []

    recomputed = _bundle_hash(pack.evidence, pack.raw_events, pack.outcome)
    bundle_hash_matches = recomputed == pack.manifest.bundle_sha256
    if not bundle_hash_matches:
        reasons.append(
            f"bundle checksum mismatch: manifest says {pack.manifest.bundle_sha256}, "
            f"recomputed {recomputed} (pack content was altered after export)"
        )

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
        )

    violations = verify_chain(list(pack.raw_events))
    chain_reverified = len(violations) == 0
    if not chain_reverified:
        reasons.extend(f"{v.kind} at seq {v.sequence}: {v.detail}" for v in violations)

    return PackVerification(
        reverified=bundle_hash_matches and chain_reverified,
        bundle_hash_matches=bundle_hash_matches,
        chain_reverified=chain_reverified,
        chain_violations=tuple(f"{v.kind}:{v.detail}" for v in violations),
        reasons=tuple(reasons),
    )


def redact_pack(pack: EvidencePack, sensitive_payload_keys: tuple[str, ...]) -> EvidencePack:
    """Return a shareable copy with the named payload keys masked in every
    embedded event. Explicitly marks the result non-independently-verifiable
    (masking breaks chain re-verification) and re-anchors the bundle checksum
    over the redacted content so the redacted pack is still tamper-evident as a
    whole -- just not chain-verifiable per event.

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

    bundle_sha256 = _bundle_hash(pack.evidence, masked, pack.outcome)
    manifest = pack.manifest.model_copy(
        update={
            "bundle_sha256": bundle_sha256,
            "independently_verifiable": False,
            "redacted_fields": tuple(sensitive_payload_keys),
            "note": (
                "REDACTED pack: named payload fields are masked, which breaks "
                "per-event hash-chain re-verification by design. This is field "
                "masking for sharing, NOT HIPAA de-identification -- remaining "
                "fields may still re-identify. The bundle checksum still detects "
                "tampering with the redacted pack as a whole."
            ),
        }
    )
    return pack.model_copy(update={"manifest": manifest, "raw_events": masked})
