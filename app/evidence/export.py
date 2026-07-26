"""Evidence-pack export + independent re-verification (Program I extension).

The strategic artifact: a self-contained, portable bundle for one decision that
a third party can verify WITHOUT Milexium's code trusting itself and WITHOUT a
live database connection -- the "machine-verifiable export" of blueprint 07.

**An honest correction to the sentence above.** `verify_evidence_pack` imports
`app.canonical`, `app.verify` and Pydantic, so for as long as it was
the only verifier, "a third party can verify this" meant "a third party can
install our code and run our verifier". Re-derivation was real; independence was
not. `app/evidence/standalone_verifier.py` is the verifier that owes this
repository nothing, and `app/evidence/pack_file.py` ships it -- and the
algorithm it implements -- inside the artifact. This module remains the in-repo
path and the two are cross-checked against each other.

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

Masking walks the WHOLE pack. ADR-0044 recorded the defect this replaced: the
mask was applied to `raw_events` only, so the same values rode out untouched in
`evidence` (the `EvidencePacket` dump, which embeds every event payload) -- a
"redacted" pack still carrying what it claimed to have removed, silently. The
walk here follows the data rather than a list of places the author remembered,
`verify_evidence_pack` RE-DERIVES whether the masking claim actually holds
instead of believing the manifest, and a post-redaction scan reports, in the
artifact itself, any value masking could not reach.

A pack may also carry a **deadhead teardown** (ADR-0039) -- the specific,
checkable finding about a partner's own operation. It is carried the same way
everything else here is carried: with its inputs embedded, so
`verify_evidence_pack` RE-DERIVES its headline figures from the segments and the
manifest's declared inputs rather than re-reading the numbers it is checking.
See `app/evidence/teardown_evidence.py`; nothing on this verification path
imports the generator.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.canonical.events import canonical_json
from app.evidence.builder import build_evidence_packet
from app.evidence.models import EvidencePacket
from app.evidence.teardown_evidence import (
    TeardownEvidence,
    redact_teardown_evidence,
    rederive_teardown,
)
from app.verify.hash_chain_verifier import verify_chain

PACK_VERSION = "0.1.0"

REDACTED_MARKER = "[REDACTED]"
"""What a masked payload value becomes, everywhere in the pack. Deliberately a
stated mask and never `None`, for the same reason
`app.evidence.teardown_evidence.REDACTED_RUN_REF` is: `None` would claim
the source never carried the field, turning a redaction into a false statement
about the data."""


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
    `app.evidence.teardown_capture.capture_teardown` -- already carrying
    its own segments, so this function embeds a finding that can be recomputed,
    not one that must be believed.
    """
    packet: EvidencePacket = build_evidence_packet(events, raw_rows, outcome=outcome)
    aggregate_id = packet.aggregate_id
    # WHY sorted: the bundle checksum is taken over these rows in the order they
    # are embedded, so a caller who happened to hand over the same history in a
    # different row order produced a DIFFERENT pack and a different
    # bundle_sha256 for identical facts. Determinism is a precondition of
    # verification, not a nicety -- if the same inputs can yield two artifacts, a
    # recipient cannot tell "re-exported" from "altered". Sorting by sequence
    # matches what build_evidence_packet already does to `events` and what
    # verify_chain already does before checking. Python's sort is stable, so
    # duplicate sequences (a real tamper case) keep their relative order and
    # remain detectable rather than being silently reconciled.
    own_rows = tuple(
        sorted(
            (row for row in raw_rows if row.get("aggregate_id") == aggregate_id),
            key=lambda row: row.get("sequence", 0),
        )
    )

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


# --------------------------------------------------------------------------- #
# Masking: one walk, used to redact and RE-DERIVED to check the redaction held  #
# --------------------------------------------------------------------------- #


def _parsed_payload(row: dict) -> object:
    """One raw event row's payload as data. `{}` when it cannot be read -- the
    pre-existing behaviour, kept: an unreadable payload is masked down to
    nothing rather than passed through unexamined."""
    try:
        return json.loads(row["payload_json"])
    except (json.JSONDecodeError, TypeError, KeyError):
        return {}


def _mask_named_keys(value: object, keys: frozenset[str]) -> object:
    """Return a copy of `value` with every named key masked WHEREVER it appears
    -- at any depth, through dicts and lists alike.

    Shape-agnostic on purpose. The defect this fixes (ADR-0044) was masking a
    remembered list of places instead of the artifact, so a payload embedded
    somewhere the masker did not know about survived redaction. A walk that
    follows the data cannot go stale when the shape of `evidence` changes.

    A named key present with a null value is masked like any other: the caller
    said this key's values do not leave, and `redact_pack` has always masked
    whatever was there.
    """
    if isinstance(value, dict):
        return {
            key: REDACTED_MARKER if key in keys else _mask_named_keys(item, keys)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_mask_named_keys(item, keys) for item in value]
    return value


def _named_payload_keys(redacted_fields: tuple[str, ...]) -> frozenset[str]:
    """The bare payload key names out of a manifest's `redacted_fields`.

    `redacted_fields` also carries structural path entries for a teardown's run
    identifiers (`teardown.segments[].run_ref`); those are not payload keys, and
    their masking is recorded by `TeardownEvidence.run_refs_redacted` and
    reported on by `rederive_teardown`, not here.
    """
    return frozenset(f for f in redacted_fields if "." not in f and "[" not in f)


def _unmasked_named_key_paths(pack: "EvidencePack", keys: frozenset[str]) -> tuple[str, ...]:
    """Every place in `pack` where a key the manifest CLAIMS is redacted still
    holds something other than the mask. Re-derived by walking the pack; the
    manifest's own claim is never the evidence for itself."""
    if not keys:
        return ()
    unmasked: list[str] = []

    def walk(node: object, path: str) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                where = f"{path}.{key}" if path else key
                if key in keys:
                    if item != REDACTED_MARKER:
                        unmasked.append(where)
                    continue
                walk(item, where)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]")

    walk(pack.evidence, "evidence")
    walk(pack.outcome, "outcome")
    for index, row in enumerate(pack.raw_events):
        walk(_parsed_payload(row), f"raw_events[{index}].payload")
    return tuple(unmasked)


def _sensitive_string_values(pack: "EvidencePack", keys: frozenset[str]) -> frozenset[str]:
    """Every non-empty string the mask is about to remove, read off the ORIGINAL
    pack so the post-redaction scan knows what to look for. Strings nested under
    a named key count: masking replaces the whole subtree, so everything in it
    is a value that must not survive anywhere."""
    if not keys:
        return frozenset()
    found: set[str] = set()

    def walk(node: object, masked: bool) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                walk(item, masked or key in keys)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item, masked)
        elif masked and isinstance(node, str) and node:
            found.add(node)

    walk(pack.evidence, False)
    walk(pack.outcome, False)
    for row in pack.raw_events:
        walk(_parsed_payload(row), False)
    return frozenset(found)


def _residual_value_paths(node: object, values: frozenset[str]) -> tuple[str, ...]:
    """Paths of every string in an already-redacted pack that still CONTAINS a
    value the masking removed.

    Reports locations only, never the value -- a leak report that quoted the
    leak would be one. Compares string values only: a masked number or boolean
    is indistinguishable from unrelated content (a sequence number, a `true`),
    and a scan that flagged those would cry wolf on every pack.
    """
    if not values:
        return ()
    found: list[str] = []

    def walk(item: object, where: str) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                walk(child, f"{where}.{key}" if where else key)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, f"{where}[{index}]")
        elif isinstance(item, str) and any(value in item for value in values):
            found.append(where or "<root>")

    walk(node, "")
    return tuple(found)


# --------------------------------------------------------------------------- #
# The manifest and the narrative are claims too, so they are re-derived         #
# --------------------------------------------------------------------------- #


def _manifest_problems(pack: "EvidencePack") -> tuple[str, ...]:
    """Every manifest claim that does not follow from the body it summarizes.

    The bundle checksum deliberately EXCLUDES the manifest -- it is where the
    checksum lives -- so at the pack layer no hash covers `event_count`,
    `aggregate_id`, `tenant_id` or `integrity_verified_at_export`. Reading them
    back left a whole surface unchecked, which is the same shape of defect
    ADR-0045 fixed for the redaction claim: a claim a verifier repeats is not a
    claim a verifier checked. Each is recomputed from `evidence` and
    `raw_events` instead.
    """
    manifest = pack.manifest
    evidence = pack.evidence if isinstance(pack.evidence, dict) else {}
    problems: list[str] = []

    if manifest.event_count != len(pack.raw_events):
        problems.append(
            f"manifest claims {manifest.event_count} events, the pack carries "
            f"{len(pack.raw_events)}"
        )
    if manifest.aggregate_id != evidence.get("aggregate_id"):
        problems.append(
            f"manifest aggregate_id {manifest.aggregate_id!r} does not match the "
            f"embedded narrative's {evidence.get('aggregate_id')!r}"
        )
    stray = sorted(
        {
            str(row.get("aggregate_id"))
            for row in pack.raw_events
            if row.get("aggregate_id") != manifest.aggregate_id
        }
    )
    if stray:
        problems.append(f"rows for other aggregates rode into this pack: {stray}")
    if manifest.tenant_id != str(evidence.get("tenant_id")):
        problems.append(
            f"manifest tenant_id {manifest.tenant_id!r} does not match the embedded "
            f"narrative's {evidence.get('tenant_id')!r}"
        )
    if manifest.integrity_verified_at_export != evidence.get("integrity_verified"):
        problems.append(
            "manifest integrity_verified_at_export disagrees with the embedded "
            "narrative's own integrity_verified"
        )

    # `integrity_verified` is itself derived: true exactly when every applicable
    # check the packet records found nothing.
    rederived = (
        not evidence.get("chain_violations")
        and not evidence.get("schema_violations")
        and (not evidence.get("state_check_applicable") or not evidence.get("state_violations"))
    )
    if bool(evidence.get("integrity_verified")) != bool(rederived):
        problems.append(
            "the narrative's integrity_verified does not follow from the violations "
            "it records"
        )
    return tuple(problems)


_NARRATIVE_SOURCES = ("known_inputs", "proposed", "approved_or_overridden", "outcome_events")


def _narrative_problems(pack: "EvidencePack") -> tuple[str, ...]:
    """Every place the reconstructed narrative does not follow from the ledger
    rows carried beside it.

    `evidence` is a reorganization of the ledger, so each event it cites must be
    one of the embedded rows. Every field the embedded record happens to carry
    is compared against that row -- following the data rather than a remembered
    list of fields, for the reason ADR-0045 gives.

    This is the only check that can see an edit to `occurred_at`: it is not an
    input to the per-event hash, so an attacker who changes it in the rows and
    re-anchors the bundle checksum passes chain re-verification and fails here,
    unless they change it identically in both places.
    """
    evidence = pack.evidence if isinstance(pack.evidence, dict) else {}
    by_event_id = {row.get("event_id"): row for row in pack.raw_events if row.get("event_id")}

    cited: list[tuple[str, dict]] = []
    for key in _NARRATIVE_SOURCES:
        value = evidence.get(key)
        if isinstance(value, list):
            cited.extend((f"evidence.{key}[{i}]", item) for i, item in enumerate(value))
    if isinstance(evidence.get("executed"), dict):
        cited.append(("evidence.executed", evidence["executed"]))

    problems: list[str] = []
    for where, record in cited:
        if not isinstance(record, dict):
            continue
        row = by_event_id.get(record.get("event_id"))
        if row is None:
            problems.append(f"{where} cites an event the carried ledger rows do not contain")
            continue
        for name, claimed in record.items():
            if name == "payload":
                actual = _parsed_payload(row)
            elif name in row:
                actual = row[name]
            else:
                continue
            if name == "occurred_at":
                if _instant(claimed) != _instant(actual):
                    problems.append(f"{where}.{name} disagrees with its ledger row")
                continue
            if isinstance(actual, str) and not isinstance(claimed, str):
                try:
                    actual = json.loads(actual)
                except json.JSONDecodeError:
                    pass
            if actual != claimed:
                problems.append(f"{where}.{name} disagrees with its ledger row")

    if pack.outcome != evidence.get("observed"):
        problems.append(
            "the pack's `outcome` and the narrative's `observed` are not the same record"
        )
    return tuple(sorted(set(problems)))


def _instant(text: object) -> datetime | None:
    """`+00:00` and `Z` are the same moment, and the ledger row and the
    reconstructed narrative legitimately spell UTC differently, so instants are
    compared as instants and never as strings."""
    if not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


class PackVerification(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reverified: bool
    bundle_hash_matches: bool
    chain_reverified: bool
    chain_violations: tuple[str, ...]
    reasons: tuple[str, ...]

    manifest_consistent: bool = True
    """RE-DERIVED: every manifest claim recomputed from the body it summarizes.
    False when the manifest describes a pack other than the one it is attached
    to -- which no checksum at the pack layer would otherwise catch, because the
    bundle hash deliberately excludes the manifest."""

    narrative_consistent: bool = True
    """RE-DERIVED: the reconstructed `evidence` narrative agrees with the raw
    ledger rows carried beside it, field by field."""

    masking_complete: bool | None = None
    """RE-DERIVED, never read from the manifest: True when every payload key the
    manifest lists as redacted is masked at EVERY occurrence in the pack, False
    when one still holds an unmasked value, None when the manifest names no
    redacted payload key (nothing to check -- deliberately distinct from "checked
    and clean"). A pack that CLAIMS a redaction it did not perform fails here."""

    unmasked_paths: tuple[str, ...] = ()
    """Where an unmasked occurrence survives. Paths only, never values."""

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

    # The manifest's redaction claim is re-derived from the pack, not believed:
    # "this was redacted" is exactly the kind of claim that failed silently
    # before (ADR-0044), so it is checked like every other claim here.
    masked_keys = _named_payload_keys(pack.manifest.redacted_fields)
    unmasked_paths = _unmasked_named_key_paths(pack, masked_keys)
    masking_complete: bool | None = None if not masked_keys else not unmasked_paths
    reasons.extend(
        f"redaction: {path} still holds an unmasked value for a key the manifest "
        "lists as redacted"
        for path in unmasked_paths
    )

    manifest_problems = _manifest_problems(pack)
    manifest_consistent = not manifest_problems
    reasons.extend(f"manifest: {problem}" for problem in manifest_problems)

    narrative_problems = _narrative_problems(pack)
    narrative_consistent = not narrative_problems
    reasons.extend(f"narrative: {problem}" for problem in narrative_problems)

    if not pack.manifest.independently_verifiable:
        reasons.append(
            "pack is marked non-independently-verifiable (redacted); chain "
            "re-verification is not possible on masked events by design"
        )
        if masked_keys:
            reasons.append(
                "redaction: the embedded EvidencePacket's per-event hashes and its "
                "integrity_verified flag were computed over the ORIGINAL payloads, "
                "so on a masked pack they record what was checked at export and are "
                "not re-checkable from these bytes"
            )
        return PackVerification(
            reverified=False,
            bundle_hash_matches=bundle_hash_matches,
            chain_reverified=False,
            chain_violations=(),
            reasons=tuple(reasons),
            masking_complete=masking_complete,
            unmasked_paths=unmasked_paths,
            manifest_consistent=manifest_consistent,
            narrative_consistent=narrative_consistent,
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
        reverified=(
            bundle_hash_matches
            and chain_reverified
            and teardown.passed
            # A pack claiming a redaction it did not perform is not re-verified,
            # whatever else holds: the claim is part of what the pack asserts.
            and masking_complete is not False
            # ...and neither is one whose manifest or narrative describes
            # something other than what it carries.
            and manifest_consistent
            and narrative_consistent
        ),
        bundle_hash_matches=bundle_hash_matches,
        chain_reverified=chain_reverified,
        chain_violations=tuple(f"{v.kind}:{v.detail}" for v in violations),
        reasons=tuple(reasons),
        masking_complete=masking_complete,
        unmasked_paths=unmasked_paths,
        manifest_consistent=manifest_consistent,
        narrative_consistent=narrative_consistent,
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

_REDACTED_EVERYWHERE_CLAUSE = (
    " Masking covers EVERY occurrence of a named key in this pack, at any "
    "nesting depth: the raw event payloads, the embedded EvidencePacket "
    "(`evidence`), and the outcome -- not raw_events alone. Consequence: that "
    "EvidencePacket's per-event hashes and its integrity_verified flag were "
    "computed over the ORIGINAL payloads, so here they record what was checked "
    "at export and are NOT re-checkable from these bytes; verify_evidence_pack "
    "reports that rather than re-running a check masked content cannot pass."
)

_REDACTION_SCAN_CLEAN = (
    " A post-redaction scan of this pack's own serialized bytes found no masked "
    "string value surviving anywhere in it. The scan compares string values "
    "only: a masked number or boolean is indistinguishable from unrelated "
    "content, so it is not scanned for."
)

_REDACTION_SCAN_RESIDUE = (
    " WARNING -- this pack is NOT fully masked: a post-redaction scan found a "
    "value the masking removed still present as free text at {paths}. Key-based "
    "masking cannot reach a value that was copied into a string elsewhere (a "
    "validation-error message quoting it, an identifier that happens to equal "
    "it). It is stated here, in the artifact, rather than left for the recipient "
    "to discover."
)

_RESIDUE_PATHS_SHOWN = 5

_REDACTED_TEARDOWN_CLAUSE = (
    " The carried teardown's run identifiers are masked in both its ranking and "
    "its embedded segments, so no run leaves in this pack. Its minute and money "
    "figures REMAIN re-derivable and are still checked (they never depended on "
    "run identity); what is lost is the fingerprint binding these segments to "
    "the original teardown. verify_evidence_pack reports that as not-checked "
    "rather than as passed."
)


def redact_pack(pack: EvidencePack, sensitive_payload_keys: tuple[str, ...]) -> EvidencePack:
    """Return a shareable copy with the named payload keys masked EVERYWHERE
    they appear -- in every embedded raw event, in the embedded EvidencePacket
    (`evidence`), and in the outcome -- and every run identifier masked in a
    carried teardown. Explicitly marks the result non-independently-verifiable
    (masking breaks chain re-verification) and re-anchors the bundle checksum
    over the redacted content so the redacted pack is still tamper-evident as a
    whole -- just not chain-verifiable per event.

    The whole-pack walk is the point (ADR-0044). Masking `raw_events` alone left
    the same values in `evidence`, which embeds every event payload, so the
    artifact built specifically to be shareable still carried what it said it
    had removed. Nothing here enumerates places to mask; it follows the data, so
    a new payload-bearing field cannot silently reopen the leak.

    Teardown run identifiers are masked unconditionally rather than on request:
    a run reference is the operator's own operational identifier, and the
    redacted pack is the copy that leaves the building. (Nothing rider-linked is
    masked because a segment structurally cannot carry anything rider-linked --
    see `app/evidence/teardown_evidence.py`.) The teardown is masked by its
    own module and is NOT walked for payload keys: its models carry fixed
    structural fields that cannot hold an event payload.

    This is field masking for sharing, NOT HIPAA de-identification: remaining
    fields may still re-identify. The manifest note says so, and also states the
    result of a post-redaction scan for any masked value the walk could not
    reach -- an incomplete redaction is reported, never left silent.
    """
    keys = frozenset(sensitive_payload_keys)
    removed_values = _sensitive_string_values(pack, keys)

    masked_events = []
    for row in pack.raw_events:
        new_row = dict(row)
        if "payload_json" in new_row:
            new_row["payload_json"] = canonical_json(
                _mask_named_keys(_parsed_payload(new_row), keys)
            )
        masked_events.append(new_row)
    masked = tuple(masked_events)

    masked_evidence = _mask_named_keys(pack.evidence, keys)
    masked_outcome = _mask_named_keys(pack.outcome, keys) if pack.outcome is not None else None

    teardown = None if pack.teardown is None else redact_teardown_evidence(pack.teardown)
    teardown_dump = teardown.model_dump(mode="json") if teardown is not None else None
    # WHY sorted: masking a set of keys is order-independent, but recording them
    # in the caller's argument order was not -- redact_pack(pack, ("a","b")) and
    # redact_pack(pack, ("b","a")) produced byte-different packs with different
    # checksums for identical masking. Same inputs, same artifact.
    redacted_fields = tuple(sorted(set(sensitive_payload_keys)))
    note = _REDACTED_NOTE + _REDACTED_EVERYWHERE_CLAUSE
    if teardown is not None:
        redacted_fields += ("teardown.top_runs[].run_ref", "teardown.segments[].run_ref")
        note += _REDACTED_TEARDOWN_CLAUSE

    bundle_sha256 = _bundle_hash(masked_evidence, masked, masked_outcome, teardown_dump)
    manifest = pack.manifest.model_copy(
        update={
            "bundle_sha256": bundle_sha256,
            "independently_verifiable": False,
            "redacted_fields": redacted_fields,
            "note": note,
        }
    )
    redacted = pack.model_copy(
        update={
            "manifest": manifest,
            "evidence": masked_evidence,
            "raw_events": masked,
            "outcome": masked_outcome,
            "teardown": teardown,
        }
    )

    # Scan the redacted pack as a recipient would read it. Only the note differs
    # between what is scanned and what is returned, and the note carries paths,
    # never values, so it can neither hide nor become a leak.
    residue = _residual_value_paths(redacted.model_dump(mode="json"), removed_values)
    if residue:
        shown = ", ".join(residue[:_RESIDUE_PATHS_SHOWN])
        if len(residue) > _RESIDUE_PATHS_SHOWN:
            shown += f" (+{len(residue) - _RESIDUE_PATHS_SHOWN} more)"
        note += _REDACTION_SCAN_RESIDUE.format(paths=shown)
    else:
        note += _REDACTION_SCAN_CLEAN
    return redacted.model_copy(
        update={"manifest": redacted.manifest.model_copy(update={"note": note})}
    )
