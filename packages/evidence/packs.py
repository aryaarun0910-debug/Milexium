"""Period, incident, and procurement evidence bundles (Program I extension).

`packages/evidence/export.py` builds one *single-aggregate* `EvidencePack` a
third party can re-verify offline (ADR-0017). A procurement or partner reviewer
almost never wants one trip in isolation -- they want the evidence covering a
*period* (blueprint 07 "Period review") or an *incident* (blueprint 07
"Incident replay"), and a structured procurement bundle they can drop into
diligence (blueprint 10 "Procurement evidence pack").

This module composes those higher-order bundles WITHOUT re-implementing any
verification: each is built from multiple single-aggregate `EvidencePack`s
produced by `build_evidence_pack`, so every embedded pack stays independently
re-verifiable by `verify_evidence_pack`, and each bundle adds only an outer
checksum over the whole. Nothing here derives a new fact about the world -- a
period pack tallies recorded events, an incident pack groups recorded packs,
neither makes a causal or performance claim.

Status: Demonstrated (built and tested on the fictional reference agency /
synthetic data). Like the single pack, these bundles are tamper-evident, not
immutable and not a compliance certificate. The procurement bundle is a
machine-readable *scaffold* that honestly separates "this repository can
substantiate this today" from "this needs external legal/ops/audit input"; it
makes no HIPAA/SOC 2/ISO/ADA compliance claim anywhere.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from packages.canonical.entities import DecisionEvent, Outcome
from packages.canonical.events import canonical_json
from packages.canonical.time import UtcDateTime
from packages.evidence.export import (
    PACK_VERSION,
    EvidencePack,
    build_evidence_pack,
    verify_evidence_pack,
)

# WHY: raw event_type strings (packages.canonical.vocab.DecisionEventType values)
# mapped to the rollup field they tally, so counts come from recorded facts.
_EVENT_TYPE_TO_ROLLUP = {
    "recommendation": "recommendations",
    "override": "overrides",
    "rejection": "denials",
    "outcome_recorded": "outcomes_recorded",
}


def _outer_bundle_hash(content: dict) -> str:
    """Deterministic checksum over a bundle's verifiable body (never its own
    manifest, which carries this hash). Reuses canonical_json -- the same
    normative serializer as the event log -- so an external re-implementation
    can reproduce it byte-for-byte, exactly as the single-pack checksum does."""
    return hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()


def _event_type_tallies(packs: Sequence[EvidencePack]) -> tuple[dict[str, int], int]:
    """Tally embedded packs' raw events by type from recorded rows -- not a
    trusted claim, a re-count of what the ledger actually holds."""
    tally = {"recommendations": 0, "overrides": 0, "denials": 0, "outcomes_recorded": 0}
    event_count = 0
    for pack in packs:
        for row in pack.raw_events:
            event_count += 1
            key = _EVENT_TYPE_TO_ROLLUP.get(row.get("event_type"))
            if key is not None:
                tally[key] += 1
    return tally, event_count


def _coverage_instants(
    packs: Sequence[EvidencePack],
) -> tuple[datetime | None, datetime | None]:
    """The actual earliest/latest event instant across embedded packs, parsed
    from raw rows so build and verify compute it from the same source."""
    stamps = [
        datetime.fromisoformat(row["occurred_at"])
        for pack in packs
        for row in pack.raw_events
        if row.get("occurred_at")
    ]
    if not stamps:
        return None, None
    return min(stamps), max(stamps)


def _build_packs(histories: Sequence["AggregateHistory"]) -> tuple[EvidencePack, ...]:
    return tuple(
        build_evidence_pack(h.events, list(h.raw_rows), h.outcome) for h in histories
    )


def _single_tenant(packs: Sequence[EvidencePack], kind: str) -> str:
    """Reject a cross-tenant bundle: mixing tenants in one evidence bundle would
    be a privacy-boundary violation (blueprint 10 tenant isolation), not a
    convenience -- so it is refused at build time, not silently allowed."""
    tenant_ids = {pack.manifest.tenant_id for pack in packs}
    if len(tenant_ids) != 1:
        raise ValueError(
            f"a {kind} evidence bundle must cover exactly one tenant; found "
            f"{sorted(tenant_ids)}"
        )
    return next(iter(tenant_ids))


class AggregateHistory(BaseModel):
    """One aggregate's raw ingredients for `build_evidence_pack` -- plain
    recorded values (events, the raw storage rows behind them, and its Outcome
    if any), never a live store handle, matching build_evidence_packet's
    backend-agnostic contract. `raw_rows` may be the whole tenant's rows;
    `build_evidence_pack` filters to this aggregate's own rows."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    events: tuple[DecisionEvent, ...]
    raw_rows: tuple[dict, ...]
    outcome: Outcome | None = None


class _Bundle(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, indent=2)

    @classmethod
    def from_json(cls, text: str):
        return cls.model_validate(json.loads(text))


# --------------------------------------------------------------------------- #
# Period evidence pack                                                        #
# --------------------------------------------------------------------------- #


class PeriodRollup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    aggregate_count: int
    event_count: int
    recommendations: int
    overrides: int
    denials: int
    outcomes_recorded: int
    note: str


class PeriodBody(BaseModel):
    """The verifiable content of a period bundle -- everything the outer
    checksum is computed over. Kept separate from the manifest so build and
    verify hash the exact same model the exact same way."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str | None
    period_start: UtcDateTime
    period_end: UtcDateTime
    covered_from: UtcDateTime | None
    covered_to: UtcDateTime | None
    rollup: PeriodRollup
    packs: tuple[EvidencePack, ...]


class PeriodManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pack_version: str
    tenant_id: str
    aggregate_count: int
    bundle_sha256: str
    independently_verifiable: bool
    note: str


class PeriodEvidencePack(_Bundle):
    """A portable evidence bundle for every decision an operator selected in a
    time window: one independently-verifiable `EvidencePack` per aggregate,
    plus a re-countable rollup and an outer checksum over the whole."""

    manifest: PeriodManifest
    body: PeriodBody


class PeriodVerification(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reverified: bool
    bundle_hash_matches: bool
    all_packs_reverified: bool
    rollup_consistent: bool
    coverage_consistent: bool
    pack_count: int
    reasons: tuple[str, ...]


_PERIOD_ROLLUP_NOTE = (
    "Tallies of recorded events across the embedded packs -- recommendations, "
    "overrides, denials (rejections), and recorded outcomes. Counts of what the "
    "ledger recorded, NOT causal or performance claims about the decisions."
)

_PERIOD_NOTE = (
    "Period evidence bundle: one independently-verifiable EvidencePack per "
    "aggregate plus a rollup that is a faithful re-count of exactly those packs. "
    "verify_period_pack re-verifies every embedded pack, re-tallies the rollup, "
    "and re-checks the outer checksum without trusting this manifest. "
    "Tamper-evident, not immutable and not a compliance certificate."
)


def build_period_pack(
    histories: Sequence[AggregateHistory],
    *,
    period_start: datetime,
    period_end: datetime,
    label: str | None = None,
) -> PeriodEvidencePack:
    """Build a period bundle from the event histories of every aggregate an
    operator selected for a window. Reuses `build_evidence_pack` per aggregate,
    so each embedded pack stays independently verifiable; adds a rollup (counts
    only) and an outer checksum over the whole body.

    `period_start`/`period_end` are the *declared* window; `covered_from`/
    `covered_to` are the actual earliest/latest recorded event instants, so a
    reviewer sees both what was asked for and what the evidence actually spans.
    Refuses an empty selection and refuses to mix tenants.
    """
    if not histories:
        raise ValueError(
            "cannot build a PeriodEvidencePack from zero aggregates; a period "
            "bundle summarizes at least one recorded decision history"
        )

    packs = _build_packs(histories)
    tenant_id = _single_tenant(packs, "period")

    tally, event_count = _event_type_tallies(packs)
    covered_from, covered_to = _coverage_instants(packs)
    rollup = PeriodRollup(
        aggregate_count=len(packs),
        event_count=event_count,
        recommendations=tally["recommendations"],
        overrides=tally["overrides"],
        denials=tally["denials"],
        outcomes_recorded=tally["outcomes_recorded"],
        note=_PERIOD_ROLLUP_NOTE,
    )
    body = PeriodBody(
        label=label,
        period_start=period_start,
        period_end=period_end,
        covered_from=covered_from,
        covered_to=covered_to,
        rollup=rollup,
        packs=packs,
    )
    manifest = PeriodManifest(
        pack_version=PACK_VERSION,
        tenant_id=tenant_id,
        aggregate_count=len(packs),
        bundle_sha256=_outer_bundle_hash(body.model_dump(mode="json")),
        # WHY: only fully verifiable if every embedded pack is (a redacted pack
        # embedded here makes the whole bundle non-independently-verifiable).
        independently_verifiable=all(
            pack.manifest.independently_verifiable for pack in packs
        ),
        note=_PERIOD_NOTE,
    )
    return PeriodEvidencePack(manifest=manifest, body=body)


def verify_period_pack(pack: PeriodEvidencePack) -> PeriodVerification:
    """Independently re-verify a period bundle from its own bytes: recompute the
    outer checksum, re-verify every embedded pack via `verify_evidence_pack`,
    re-tally the rollup, and re-derive the covered range. None of these trust
    the manifest -- all recompute from the embedded packs' source rows."""
    reasons: list[str] = []

    recomputed = _outer_bundle_hash(pack.body.model_dump(mode="json"))
    bundle_hash_matches = recomputed == pack.manifest.bundle_sha256
    if not bundle_hash_matches:
        reasons.append(
            f"period bundle checksum mismatch: manifest says "
            f"{pack.manifest.bundle_sha256}, recomputed {recomputed} (bundle "
            f"content was altered after export)"
        )

    pack_results = [verify_evidence_pack(embedded) for embedded in pack.body.packs]
    all_packs_reverified = all(result.reverified for result in pack_results)
    for embedded, result in zip(pack.body.packs, pack_results):
        if not result.reverified:
            reasons.extend(
                f"embedded pack {embedded.manifest.aggregate_id}: {reason}"
                for reason in result.reasons
            )

    tally, event_count = _event_type_tallies(pack.body.packs)
    rollup = pack.body.rollup
    rollup_consistent = (
        rollup.aggregate_count == len(pack.body.packs)
        and rollup.event_count == event_count
        and rollup.recommendations == tally["recommendations"]
        and rollup.overrides == tally["overrides"]
        and rollup.denials == tally["denials"]
        and rollup.outcomes_recorded == tally["outcomes_recorded"]
    )
    if not rollup_consistent:
        reasons.append(
            "period rollup counts do not match a re-tally of the embedded packs "
            "(the rollup was altered or never honestly summarized these packs)"
        )

    covered_from, covered_to = _coverage_instants(pack.body.packs)
    coverage_consistent = (
        covered_from == pack.body.covered_from and covered_to == pack.body.covered_to
    )
    if not coverage_consistent:
        reasons.append(
            "period covered_from/covered_to do not match the embedded packs' "
            "recorded event timestamps"
        )

    reverified = (
        bundle_hash_matches
        and all_packs_reverified
        and rollup_consistent
        and coverage_consistent
    )
    return PeriodVerification(
        reverified=reverified,
        bundle_hash_matches=bundle_hash_matches,
        all_packs_reverified=all_packs_reverified,
        rollup_consistent=rollup_consistent,
        coverage_consistent=coverage_consistent,
        pack_count=len(pack.body.packs),
        reasons=tuple(reasons),
    )


# --------------------------------------------------------------------------- #
# Incident evidence pack                                                       #
# --------------------------------------------------------------------------- #


class IncidentBody(BaseModel):
    """The verifiable content of an incident bundle. `primary_packs` are the
    aggregate(s) the incident is directly about; `related_packs` are the
    surrounding context (e.g. same vehicle/day). Both are ordinary
    independently-verifiable EvidencePacks."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    incident_id: str
    summary: str
    context_note: str | None
    primary_packs: tuple[EvidencePack, ...]
    related_packs: tuple[EvidencePack, ...]


class IncidentManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pack_version: str
    tenant_id: str
    incident_id: str
    primary_count: int
    related_count: int
    bundle_sha256: str
    independently_verifiable: bool
    note: str


class IncidentEvidencePack(_Bundle):
    """A portable evidence bundle centered on one incident: the decision(s)
    directly involved plus their surrounding context, each an independently-
    verifiable `EvidencePack` embedding the full known/proposed/verified/
    overridden/observed narrative, under one outer checksum."""

    manifest: IncidentManifest
    body: IncidentBody


class IncidentVerification(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reverified: bool
    bundle_hash_matches: bool
    all_packs_reverified: bool
    primary_count: int
    related_count: int
    reasons: tuple[str, ...]


_INCIDENT_NOTE = (
    "Incident evidence bundle: the primary aggregate(s) directly involved plus "
    "related-context aggregates, each an independently-verifiable EvidencePack "
    "embedding the full known/proposed/verified/overridden/observed narrative. "
    "context_note records how the related set was selected (e.g. same vehicle/"
    "day) -- a recorded selection criterion, never a causal claim. "
    "verify_incident_pack re-verifies every embedded pack and the outer "
    "checksum. Tamper-evident, not immutable and not a compliance certificate."
)


def build_incident_pack(
    *,
    incident_id: str,
    summary: str,
    primary: Sequence[AggregateHistory],
    related: Sequence[AggregateHistory] = (),
    context_note: str | None = None,
) -> IncidentEvidencePack:
    """Build an incident bundle from the disputed aggregate(s) (`primary`) and
    their surrounding context (`related`). Reuses `build_evidence_pack` per
    aggregate so each embedded pack stays independently verifiable, and adds an
    outer checksum over the whole. `summary`/`context_note` are recorded prose,
    never a derived conclusion. Refuses an empty primary set and refuses to mix
    tenants."""
    if not primary:
        raise ValueError(
            "cannot build an IncidentEvidencePack with no primary aggregate; an "
            "incident bundle centers on at least one directly-involved decision"
        )

    primary_packs = _build_packs(primary)
    related_packs = _build_packs(related)
    all_packs = primary_packs + related_packs
    tenant_id = _single_tenant(all_packs, "incident")

    body = IncidentBody(
        incident_id=incident_id,
        summary=summary,
        context_note=context_note,
        primary_packs=primary_packs,
        related_packs=related_packs,
    )
    manifest = IncidentManifest(
        pack_version=PACK_VERSION,
        tenant_id=tenant_id,
        incident_id=incident_id,
        primary_count=len(primary_packs),
        related_count=len(related_packs),
        bundle_sha256=_outer_bundle_hash(body.model_dump(mode="json")),
        independently_verifiable=all(
            pack.manifest.independently_verifiable for pack in all_packs
        ),
        note=_INCIDENT_NOTE,
    )
    return IncidentEvidencePack(manifest=manifest, body=body)


def verify_incident_pack(pack: IncidentEvidencePack) -> IncidentVerification:
    """Independently re-verify an incident bundle from its own bytes: recompute
    the outer checksum and re-verify every embedded pack (primary and related)
    via `verify_evidence_pack`. Neither check trusts the manifest."""
    reasons: list[str] = []

    recomputed = _outer_bundle_hash(pack.body.model_dump(mode="json"))
    bundle_hash_matches = recomputed == pack.manifest.bundle_sha256
    if not bundle_hash_matches:
        reasons.append(
            f"incident bundle checksum mismatch: manifest says "
            f"{pack.manifest.bundle_sha256}, recomputed {recomputed} (bundle "
            f"content was altered after export)"
        )

    all_packs = pack.body.primary_packs + pack.body.related_packs
    pack_results = [verify_evidence_pack(embedded) for embedded in all_packs]
    all_packs_reverified = all(result.reverified for result in pack_results)
    for embedded, result in zip(all_packs, pack_results):
        if not result.reverified:
            reasons.extend(
                f"embedded pack {embedded.manifest.aggregate_id}: {reason}"
                for reason in result.reasons
            )

    reverified = bundle_hash_matches and all_packs_reverified
    return IncidentVerification(
        reverified=reverified,
        bundle_hash_matches=bundle_hash_matches,
        all_packs_reverified=all_packs_reverified,
        primary_count=len(pack.body.primary_packs),
        related_count=len(pack.body.related_packs),
        reasons=tuple(reasons),
    )


# --------------------------------------------------------------------------- #
# Procurement evidence bundle                                                  #
# --------------------------------------------------------------------------- #

ProcurementStatus = Literal["available", "partial", "not_yet_available"]


class ProcurementItem(BaseModel):
    """One line of the blueprint-10 procurement evidence pack, with an honest
    status. `available`: this repository substantiates it today. `partial`:
    substantiated in part, with a stated remainder. `not_yet_available`: a
    placeholder that requires external legal/ops/audit input -- never fabricated
    compliance content."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    title: str
    status: ProcurementStatus
    requires_external_input: bool
    references: tuple[str, ...] = ()
    note: str


class ProcurementBundle(_Bundle):
    """Machine-readable scaffold of the blueprint-10 procurement evidence pack
    that honestly separates what this repository can substantiate from what
    needs external input. Makes NO compliance claim (no HIPAA/SOC 2/ISO/ADA)."""

    bundle_version: str
    generated_for: str
    disclaimer: str
    items: tuple[ProcurementItem, ...]

    @property
    def available(self) -> tuple[ProcurementItem, ...]:
        return tuple(i for i in self.items if i.status == "available")

    @property
    def partial(self) -> tuple[ProcurementItem, ...]:
        return tuple(i for i in self.items if i.status == "partial")

    @property
    def not_yet_available(self) -> tuple[ProcurementItem, ...]:
        return tuple(i for i in self.items if i.status == "not_yet_available")


_PROCUREMENT_DISCLAIMER = (
    "This bundle enumerates the blueprint-10 procurement evidence pack items and "
    "marks, per item, whether this repository can substantiate it today. It makes "
    "NO compliance claim: nothing here asserts HIPAA, SOC 2, ISO, or ADA "
    "compliance. Items marked not_yet_available are honest placeholders requiring "
    "external legal, security-audit, or operations input -- they are declared "
    "gaps, not hidden ones. Status is Demonstrated on fictional/synthetic data."
)

# WHY: the blueprint-10 procurement list (lines 186-198), each mapped to what
# this repository can honestly substantiate today -- available/partial with real
# references, or not_yet_available (requires_external_input) with no fabricated
# content. Reviewed against the actual repo, not aspirationally.
_PROCUREMENT_ITEMS: tuple[ProcurementItem, ...] = (
    ProcurementItem(
        key="architecture_data_flow",
        title="Architecture and data-flow diagrams",
        status="available",
        requires_external_input=False,
        references=(
            "architecture/decisions/",
            "packages/canonical/entities.py",
            "packages/connect/",
        ),
        note=(
            "ADR corpus, the canonical entity schema, and the adapter set "
            "document the components and source-to-canonical data flow at "
            "code/ADR level; a separately rendered diagram artifact is not "
            "produced."
        ),
    ),
    ProcurementItem(
        key="data_inventory_classification_retention",
        title="Data inventory/classification and retention",
        status="partial",
        requires_external_input=False,
        references=(
            "docs/DATA_SOURCES.md",
            "docs/DATA_STORAGE.md",
            "packages/estate/",
            "packages/canonical/vocab.py",
        ),
        note=(
            "A data inventory (estate catalog + DATA_SOURCES) and a field-level "
            "sensitivity/classification vocabulary (SensitivityClass) exist; a "
            "per-class retention/deletion policy is not yet defined."
        ),
    ),
    ProcurementItem(
        key="threat_model_control_mapping",
        title="Threat model and control mapping",
        status="partial",
        requires_external_input=False,
        references=(
            "conformance/adversarial/test_tamper_and_isolation.py",
            "packages/verify/",
        ),
        note=(
            "Adversarial tests exercise several named threats (cross-tenant "
            "access, evidence tampering, malformed imports); a complete written "
            "threat model with full preventive/detective/recovery control "
            "mapping is not yet assembled in this repository."
        ),
    ),
    ProcurementItem(
        key="subprocessor_deployment_list",
        title="Subprocessor and deployment list",
        status="not_yet_available",
        requires_external_input=True,
        references=(),
        note=(
            "No subprocessors are engaged in this repository's local/demo "
            "posture; a real subprocessor and deployment list depends on hosting "
            "and vendor contracts. Requires ops/legal input."
        ),
    ),
    ProcurementItem(
        key="encryption_key_management",
        title="Encryption/key management summary",
        status="not_yet_available",
        requires_external_input=True,
        references=(),
        note=(
            "No managed KMS, TLS termination, or at-rest encryption is "
            "configured in this local/demo repository; requires deployment/ops "
            "input. (Evidence payloads deliberately carry no keys or "
            "credentials, per blueprint 10.)"
        ),
    ),
    ProcurementItem(
        key="access_control_matrix",
        title="Access-control matrix",
        status="partial",
        requires_external_input=False,
        references=(
            "packages/canonical/storage.py",
            "conformance/adversarial/test_tamper_and_isolation.py",
        ),
        note=(
            "Tenant-scoped data access is enforced by WHERE-clause isolation and "
            "adversarially tested; a full role/service-identity access-control "
            "matrix (RBAC, MFA/SSO, support access) requires deployment input."
        ),
    ),
    ProcurementItem(
        key="secure_development_policy",
        title="Secure-development policy",
        status="partial",
        requires_external_input=False,
        references=(
            "architecture/decisions/",
            "conformance/",
            "third_party/VENDORING_PROCESS.md",
        ),
        note=(
            "ADR-gated changes, generator/verifier separation, a conformance/"
            "adversarial test suite, and a vendoring-review gate exist; formal "
            "SSDF items (CI security/secret/dependency scanning, signed "
            "releases, supported-version policy) are not yet configured."
        ),
    ),
    ProcurementItem(
        key="vulnerability_disclosure_incident_process",
        title="Vulnerability disclosure and incident process",
        status="not_yet_available",
        requires_external_input=True,
        references=(),
        note=(
            "No security.txt, disclosure address, or incident-response runbook "
            "exists in this repository; requires ops/legal input."
        ),
    ),
    ProcurementItem(
        key="backup_restore_results",
        title="Backup/restore results",
        status="not_yet_available",
        requires_external_input=True,
        references=(),
        note=(
            "No managed database, backups, or restore drills exist in this "
            "local/demo posture; requires deployment/ops input."
        ),
    ),
    ProcurementItem(
        key="model_policy_governance",
        title="Model/policy governance",
        status="available",
        requires_external_input=False,
        references=(
            "packages/core/",
            "docs/MODEL_CARDS.md",
            "packages/canonical/entities.py",
        ),
        note=(
            "A model registry with versioned ModelVersion/Policy entities and "
            "champion selection, plus model cards, provide the model and policy "
            "governance pointers; named accountable owners per model are not yet "
            "assigned."
        ),
    ),
    ProcurementItem(
        key="accessibility_statement",
        title="Accessibility statement",
        status="not_yet_available",
        requires_external_input=True,
        references=(),
        note=(
            "This repository contains no product UI (the website/console is "
            "owned separately); an accessibility statement (WCAG conformance) "
            "requires the UI owner's input."
        ),
    ),
    ProcurementItem(
        key="current_certifications",
        title="Current certifications with exact scope",
        status="not_yet_available",
        requires_external_input=True,
        references=(),
        note=(
            "None. No SOC 2, HIPAA, ISO, or other certification has been "
            "obtained or audited. This item is intentionally empty; any "
            "certification claim requires a completed external audit."
        ),
    ),
    ProcurementItem(
        key="known_gaps_remediation",
        title="Known gaps and remediation plan",
        status="available",
        requires_external_input=False,
        references=(
            "IMPLEMENTATION_STATUS.md",
        ),
        note=(
            "IMPLEMENTATION_STATUS.md's honest status ledger and 'Genuine "
            "blockers' section, together with the not_yet_available items in "
            "this bundle, constitute the current known-gaps and remediation "
            "surface."
        ),
    ),
)


def build_procurement_bundle(generated_for: str = "reference") -> ProcurementBundle:
    """Build the procurement evidence scaffold: the blueprint-10 item list with
    an honest per-item status. `generated_for` is a free-form label (e.g. a
    tenant or organization name) for the reviewer's record. The content is a
    fixed, current, honest assessment of this repository -- no compliance claim
    is made or implied."""
    return ProcurementBundle(
        bundle_version=PACK_VERSION,
        generated_for=generated_for,
        disclaimer=_PROCUREMENT_DISCLAIMER,
        items=_PROCUREMENT_ITEMS,
    )
