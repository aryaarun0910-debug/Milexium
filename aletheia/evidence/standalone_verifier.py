"""The evidence-pack verifier a third party runs -- with no Milexium code.

This module is the reference verifier, and it is written under one hard rule:
**it imports nothing from this repository.** Only the Python standard library
(`argparse`, `dataclasses`, `datetime`, `hashlib`, `json`, `sys`). That rule is
the whole point, and it is asserted against this module's AST in
`aletheia/conformance/property-tests/test_pack_standalone_verifier.py`, not merely stated
here.

Why it matters. `aletheia/evidence/export.py` already offers
`verify_evidence_pack`, and ADR-0017 called the pack "independently
verifiable" on the strength of it. But that function imports
`themis.canonical.events.canonical_json`, `aletheia.verify.hash_chain_verifier`
and Pydantic, so a reviewer holding the pack still had to install and trust
*our* code to check *our* claim. That is a report, not verification. This module
is the honest version: its source text is **carried inside the pack file**
(`aletheia/evidence/pack_file.py`), extractable with `python -m json.tool`-level
tooling and runnable on a stock CPython with nothing installed:

    python verify_milexium_pack.py evidence-pack.json

Exit code 0 means every check the artifact claims to support passed; 1 means at
least one failed or could not be checked; 2 means the file could not be read.

**What this verifier can and cannot establish.** It re-derives arithmetic and
integrity: that the bytes were not altered after export, that the hash chain
recomputes, that the narrative in `evidence` follows from the ledger rows the
pack carries, that a manifest's summary of its own body is true, that a claimed
redaction was actually performed, and that a carried teardown's figures follow
from its embedded segments and declared inputs. It establishes NOTHING about
whether those inputs describe a real operation -- see the `attestation` block,
which is machine-readable precisely so that limit is checkable rather than
prose. This verifier FAILS a pack file whose attestation overclaims.

**The one thing this script cannot vouch for is itself.** A tampered pack could
carry a tampered verifier that reports success. `verifier.sha256` is recomputed
here, but by the same possibly-tampered code. A reviewer who wants that closed
compares the digest against one obtained from Milexium separately, or reads the
script -- it is deliberately short enough to read, and `pack_file.algorithm`
states every normative rule needed to reimplement it from scratch in any
language. Self-checking is a convenience; the independent path is the algorithm
spec.

Status: Demonstrated (exercised on the fictional reference agency / synthetic
and public data). Nothing here is Validated: no consented operator data exists.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta

VERIFIER_VERSION = "0.1.0"
VERIFIER_FILENAME = "verify_milexium_pack.py"

REDACTED_MARKER = "[REDACTED]"
"""What a masked value is, everywhere. Never `None`: `None` would claim the
source never carried the field, turning a redaction into a false statement."""

# The teardown generator emits figures rounded to 6 decimal places, so an honest
# figure differs from an exact re-derivation by at most 5e-7 plus float
# summation-order noise that scales with magnitude. A tamper smaller than this
# is invisible to the arithmetic check -- but not to the bundle checksum, which
# catches any byte change at all.
_ROUNDING_SLACK = 1e-6
_RELATIVE_SLACK = 1e-9

_SEGMENT_KINDS = ("revenue", "deadhead")

# A pack file must never assert any of these. They are refusals, not defaults:
# this repository holds no consented operator data, so an artifact leaving it
# cannot claim to reflect operational reality (ADR-0039's absent "operator"
# provenance, applied to the whole artifact).
_FORBIDDEN_ATTESTATIONS = (
    "reflects_operational_reality",
    "consented_operator_input",
    "operator_data_present",
    "causal_claim",
)
_FORBIDDEN_STATUSES = ("Validated", "Production")
_ALLOWED_PROVENANCE = ("real_public", "synthetic", "mixed")


# --------------------------------------------------------------------------- #
# Normative primitives -- reimplement these three and everything else follows   #
# --------------------------------------------------------------------------- #


def canonical_json(payload: object) -> str:
    """The repository's normative deterministic serialization: keys sorted, no
    incidental whitespace, ASCII-escaped. Every hash below is taken over the
    UTF-8 bytes of this. Reproduce it exactly or nothing will match."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_event_hash(
    prev_hash: str | None,
    payload: object,
    sequence: int,
    aggregate_id: str,
    idempotency_key: str | None,
) -> str:
    """The normative per-event hash: sha256 over the concatenation, in this
    exact order, of prev_hash (empty string when absent), the canonical JSON of
    the payload, the decimal sequence number, the aggregate id, and the
    idempotency key (empty string when absent) -- each UTF-8 encoded."""
    digest = hashlib.sha256()
    digest.update((prev_hash or "").encode("utf-8"))
    digest.update(canonical_json(payload).encode("utf-8"))
    digest.update(str(sequence).encode("utf-8"))
    digest.update(aggregate_id.encode("utf-8"))
    digest.update((idempotency_key or "").encode("utf-8"))
    return digest.hexdigest()


def bundle_hash(
    evidence: object, raw_events: list, outcome: object, teardown: object | None
) -> str:
    """The pack's own checksum: sha256 over the canonical JSON of
    `{"evidence":..., "raw_events":[...], "outcome":...}`, with a `"teardown"`
    key added ONLY when a teardown is carried. The manifest is deliberately
    outside this hash -- it is where the hash lives."""
    payload = {"evidence": evidence, "raw_events": list(raw_events), "outcome": outcome}
    if teardown is not None:
        payload["teardown"] = teardown
    return sha256_hex(canonical_json(payload))


def segment_fingerprint(segments: list) -> str:
    """The order-independent segment fingerprint: take `[started_at, ended_at,
    kind, run_ref]` for every segment, sort those four-element lists by
    `(started_at, ended_at, kind, run_ref or "")`, then sha256 the canonical
    JSON of `{"segments": [...]}`."""
    rows = [
        [s.get("started_at"), s.get("ended_at"), s.get("kind"), s.get("run_ref")]
        for s in segments
    ]
    rows.sort(key=lambda row: (row[0] or "", row[1] or "", row[2] or "", row[3] or ""))
    return sha256_hex(canonical_json({"segments": rows}))


# --------------------------------------------------------------------------- #
# Result model                                                                 #
# --------------------------------------------------------------------------- #

PASS = "pass"
FAIL = "fail"
NOT_APPLICABLE = "not_applicable"
NOT_CHECKABLE = "not_checkable_by_design"


@dataclass
class Check:
    """One named, re-derived check. `detail` never quotes a payload value: a
    verification report that leaked what a redaction removed would itself be the
    leak."""

    check_id: str
    status: str
    detail: str = ""

    def as_dict(self) -> dict:
        return {"check_id": self.check_id, "status": self.status, "detail": self.detail}


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, check_id: str, status: str, detail: str = "") -> None:
        self.checks.append(Check(check_id, status, detail))

    def ok(self, check_id: str, ok: bool, detail: str = "") -> bool:
        self.add(check_id, PASS if ok else FAIL, "" if ok else detail)
        return ok

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if c.status == FAIL]

    @property
    def unavailable(self) -> list[Check]:
        return [c for c in self.checks if c.status == NOT_CHECKABLE]

    @property
    def verified(self) -> bool:
        """True only when nothing failed AND nothing was skipped-by-design. A
        check we could not run is never reported as a check that passed."""
        return not self.failures and not self.unavailable

    def as_dict(self) -> dict:
        return {
            "verifier_version": VERIFIER_VERSION,
            "verified": self.verified,
            "checks": [c.as_dict() for c in self.checks],
            "failed": [c.check_id for c in self.failures],
            "not_checkable": [c.check_id for c in self.unavailable],
        }


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _close(claimed: float, rederived: float) -> bool:
    return abs(claimed - rederived) <= _ROUNDING_SLACK + abs(rederived) * _RELATIVE_SLACK


def _instant(text: object) -> datetime | None:
    """Parse an ISO-8601 instant. `+00:00` and `Z` are the same moment and the
    pack legitimately carries both spellings (the raw ledger row and the
    reconstructed narrative format them differently), so instants are compared
    as instants and never as strings."""
    if not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _loads(text: object) -> object:
    if not isinstance(text, str):
        return text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _mask_paths(node: object, keys: set, path: str, found: list) -> None:
    """Every place a named key still holds something other than the mask."""
    if isinstance(node, dict):
        for key, item in node.items():
            where = f"{path}.{key}" if path else str(key)
            if key in keys:
                if item != REDACTED_MARKER:
                    found.append(where)
                continue
            _mask_paths(item, keys, where, found)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            _mask_paths(item, keys, f"{path}[{index}]", found)


def _minutes(row: dict) -> float | None:
    start = _instant(row.get("started_at"))
    end = _instant(row.get("ended_at"))
    if start is None or end is None:
        return None
    return (end - start).total_seconds() / 60.0


def _hour_slices(start: datetime, end: datetime) -> list:
    """Split a span at hour boundaries so its minutes land in the hours they
    actually fell in: 09:50-10:20 gives 10 minutes to hour 09 and 20 to hour 10."""
    out = []
    cursor = start
    while cursor < end:
        hour_start = cursor.replace(minute=0, second=0, microsecond=0)
        slice_end = min(hour_start + timedelta(hours=1), end)
        out.append((hour_start, (slice_end - cursor).total_seconds() / 60.0))
        cursor = slice_end
    return out


def _share(part: float, whole: float) -> float | None:
    if whole <= 0:
        return None
    return part / whole


# --------------------------------------------------------------------------- #
# Attestation: the pack must not claim more than it can support                 #
# --------------------------------------------------------------------------- #


def check_attestation(attestation: object, report: Report) -> None:
    """Re-derive that the artifact's own scope declaration stays inside what an
    evidence pack can support. This is the machine-readable half of "honest
    about what it cannot prove": a pack file that asserts operational reality,
    consented operator input, or a Validated/Production status FAILS here, so
    the modesty is enforced by the verifier a third party runs and not by prose
    a reader is trusted to notice."""
    if not isinstance(attestation, dict):
        report.add(
            "attestation.present",
            FAIL,
            "the pack file carries no machine-readable attestation block, so its "
            "scope cannot be checked and must not be assumed narrow",
        )
        return
    report.add("attestation.present", PASS)

    for name in _FORBIDDEN_ATTESTATIONS:
        value = attestation.get(name)
        report.ok(
            f"attestation.{name}_is_false",
            value is False,
            f"{name} is {value!r}; an evidence pack built without consented "
            "operator data may never assert it (it must be present and False)",
        )

    status = attestation.get("status")
    report.ok(
        "attestation.status_not_overclaimed",
        status not in _FORBIDDEN_STATUSES,
        f"status {status!r} is an overclaim: no consented operator data exists, "
        f"so nothing in this artifact can be {status!r}",
    )

    provenance = attestation.get("data_provenance")
    report.ok(
        "attestation.data_provenance_known",
        provenance in _ALLOWED_PROVENANCE,
        f"data_provenance {provenance!r} is not one of {_ALLOWED_PROVENANCE}; in "
        "particular there is no 'operator' provenance to claim",
    )

    report.ok(
        "attestation.states_what_it_cannot_prove",
        bool(attestation.get("does_not_attest")),
        "does_not_attest is empty: an artifact that lists no limit is claiming "
        "there are none",
    )
    report.ok(
        "attestation.computation_follows_from_inputs",
        attestation.get("computation_follows_from_inputs") is True,
        "the one thing a pack CAN attest -- that its computation follows from "
        "the inputs it carries -- is not asserted",
    )


# --------------------------------------------------------------------------- #
# Pack: manifest, narrative, chain, redaction                                   #
# --------------------------------------------------------------------------- #


def _check_manifest(pack: dict, report: Report) -> None:
    """Re-derive every manifest claim from the body it summarizes.

    The bundle checksum deliberately excludes the manifest (it is where the
    checksum lives), so manifest fields are covered by NO hash at the pack
    layer. Believing them would leave a whole surface unchecked -- so each one
    is recomputed from `evidence` and `raw_events` instead.
    """
    manifest = pack.get("manifest") or {}
    evidence = pack.get("evidence") or {}
    raw_events = pack.get("raw_events") or []

    report.ok(
        "manifest.event_count",
        manifest.get("event_count") == len(raw_events),
        f"manifest says {manifest.get('event_count')!r} events, the pack carries "
        f"{len(raw_events)}",
    )

    aggregate_id = manifest.get("aggregate_id")
    report.ok(
        "manifest.aggregate_id_matches_evidence",
        aggregate_id == evidence.get("aggregate_id"),
        f"manifest aggregate_id {aggregate_id!r} does not match the embedded "
        f"narrative's {evidence.get('aggregate_id')!r}",
    )
    stray = sorted(
        {
            str(row.get("aggregate_id"))
            for row in raw_events
            if row.get("aggregate_id") != aggregate_id
        }
    )
    report.ok(
        "manifest.aggregate_id_matches_every_row",
        not stray,
        f"rows for other aggregates rode into this pack: {stray}",
    )

    report.ok(
        "manifest.tenant_id_matches_evidence",
        str(manifest.get("tenant_id")) == str(evidence.get("tenant_id")),
        f"manifest tenant_id {manifest.get('tenant_id')!r} does not match the "
        f"embedded narrative's {evidence.get('tenant_id')!r}",
    )

    report.ok(
        "manifest.integrity_flag_matches_evidence",
        manifest.get("integrity_verified_at_export") == evidence.get("integrity_verified"),
        "manifest.integrity_verified_at_export disagrees with the embedded "
        "narrative's own integrity_verified",
    )

    # `integrity_verified` is itself a derived claim: it is true exactly when
    # every applicable check the packet records found nothing.
    rederived_integrity = (
        not evidence.get("chain_violations")
        and not evidence.get("schema_violations")
        and (
            not evidence.get("state_check_applicable")
            or not evidence.get("state_violations")
        )
    )
    report.ok(
        "evidence.integrity_flag_follows_from_its_violations",
        bool(evidence.get("integrity_verified")) == bool(rederived_integrity),
        "the narrative's integrity_verified does not follow from the violations "
        "it records",
    )


def _check_narrative_against_ledger(pack: dict, report: Report) -> None:
    """The reconstructed narrative must follow from the primitive rows.

    `evidence` is a *reorganization* of the ledger; every event it cites is
    supposed to be one of the rows carried alongside it. So each embedded event
    record is matched to its raw row by `event_id` and every field it happens to
    carry is compared -- not a remembered list of fields. (ADR-0045's lesson:
    enumerate the data, never the places.)

    This is what catches an edit the per-event hash cannot see. `occurred_at` is
    NOT an input to the event hash, so an attacker who changes it and re-anchors
    the bundle checksum passes the chain check; they do not pass this one unless
    they change it identically in both places.
    """
    evidence = pack.get("evidence") or {}
    raw_events = pack.get("raw_events") or []
    by_event_id = {row.get("event_id"): row for row in raw_events if row.get("event_id")}

    embedded: list = []
    for key in ("known_inputs", "proposed", "approved_or_overridden", "outcome_events"):
        value = evidence.get(key)
        if isinstance(value, list):
            embedded.extend((f"evidence.{key}[{i}]", item) for i, item in enumerate(value))
    if isinstance(evidence.get("executed"), dict):
        embedded.append(("evidence.executed", evidence["executed"]))

    if not embedded:
        report.add(
            "narrative.matches_ledger",
            NOT_APPLICABLE,
            "the narrative cites no individual events",
        )
        return

    problems: list[str] = []
    for where, record in embedded:
        if not isinstance(record, dict):
            continue
        event_id = record.get("event_id")
        row = by_event_id.get(event_id)
        if row is None:
            problems.append(f"{where} cites an event the carried ledger rows do not contain")
            continue
        for field_name, claimed in record.items():
            if field_name == "payload":
                actual = _loads(row.get("payload_json"))
            elif field_name in row:
                actual = row[field_name]
            else:
                continue
            if field_name == "occurred_at":
                if _instant(claimed) != _instant(actual):
                    problems.append(f"{where}.{field_name} disagrees with the ledger row")
                continue
            # The ledger row stores some structured fields as JSON text
            # (reason_codes) where the narrative holds them as values; parse the
            # row's side only when the shapes actually differ, so a scalar is
            # never coerced into agreeing with a different scalar.
            if isinstance(actual, str) and not isinstance(claimed, str):
                actual = _loads(actual)
            if actual != claimed:
                problems.append(f"{where}.{field_name} disagrees with the ledger row")

    report.ok(
        "narrative.matches_ledger",
        not problems,
        "; ".join(sorted(set(problems))),
    )

    # The recorded outcome must be the same object in both places.
    outcome = pack.get("outcome")
    observed = evidence.get("observed")
    report.ok(
        "narrative.outcome_matches_pack_outcome",
        outcome == observed,
        "the pack's `outcome` and the narrative's `observed` are not the same record",
    )


def _check_chain(pack: dict, report: Report) -> None:
    """Recompute every event hash from the raw rows and re-walk the links."""
    raw_events = list(pack.get("raw_events") or [])
    if not raw_events:
        report.add("chain.rehashed", NOT_APPLICABLE, "the pack carries no ledger rows")
        return

    problems: list[str] = []
    rows = sorted(raw_events, key=lambda r: r.get("sequence", 0))
    expected_sequence = 1
    expected_prev: str | None = None
    seen: set = set()
    for row in rows:
        sequence = row.get("sequence")
        if sequence in seen:
            problems.append(f"sequence {sequence} appears more than once")
            continue
        seen.add(sequence)
        if sequence != expected_sequence:
            problems.append(f"expected sequence {expected_sequence}, found {sequence}")
        if row.get("prev_hash") != expected_prev:
            problems.append(f"sequence {sequence}: prev_hash does not link to the row before it")
        recomputed = compute_event_hash(
            row.get("prev_hash"),
            _loads(row.get("payload_json")),
            sequence,
            str(row.get("aggregate_id")),
            row.get("idempotency_key"),
        )
        if recomputed != row.get("hash"):
            problems.append(
                f"sequence {sequence}: recomputed {recomputed} != stored {row.get('hash')}"
            )
        expected_sequence = (sequence or 0) + 1
        expected_prev = row.get("hash")

    report.ok("chain.rehashed", not problems, "; ".join(problems))

    # The narrative records its own chain verdict; ours must agree with it.
    recorded = (pack.get("evidence") or {}).get("chain_violations")
    report.ok(
        "chain.matches_recorded_verdict",
        bool(problems) == bool(recorded),
        "the narrative's recorded chain_violations disagree with an independent "
        "re-walk of the same rows",
    )


def _check_redaction(pack: dict, report: Report) -> None:
    """Re-derive the redaction claim rather than believing it (ADR-0045)."""
    manifest = pack.get("manifest") or {}
    declared = manifest.get("redacted_fields") or ()
    keys = {f for f in declared if isinstance(f, str) and "." not in f and "[" not in f}
    if not keys:
        report.add(
            "redaction.claim_holds",
            NOT_APPLICABLE,
            "the manifest names no redacted payload key",
        )
        return

    found: list[str] = []
    _mask_paths(pack.get("evidence"), keys, "evidence", found)
    _mask_paths(pack.get("outcome"), keys, "outcome", found)
    for index, row in enumerate(pack.get("raw_events") or []):
        _mask_paths(_loads(row.get("payload_json")), keys, f"raw_events[{index}].payload", found)

    report.ok(
        "redaction.claim_holds",
        not found,
        "a key the manifest lists as redacted still holds an unmasked value at: "
        + ", ".join(found),
    )


# --------------------------------------------------------------------------- #
# Teardown re-derivation                                                       #
# --------------------------------------------------------------------------- #


def _declared_inputs(manifest: dict) -> dict:
    out = {}
    for record in manifest.get("inputs") or ():
        if isinstance(record, dict) and "name" in record and "value" in record:
            out[str(record["name"])] = str(record["value"])
    return out


def _check_teardown_cost(figures: dict, declared: dict, total_deadhead: float, report: Report) -> None:
    rate_text = declared.get("cost_per_vehicle_hour")
    claims_envelope = (
        figures.get("modelled_envelope_low") is not None
        or figures.get("modelled_envelope_high") is not None
    )
    claims_money = (
        figures.get("value_at_full_cost") is not None
        or figures.get("deadhead_hours") is not None
        or claims_envelope
    )

    if rate_text is None:
        report.ok(
            "teardown.money_has_a_declared_basis",
            not claims_money,
            "a money figure is claimed but the manifest declares no "
            "cost_per_vehicle_hour input to re-derive it from",
        )
        return
    report.add("teardown.money_has_a_declared_basis", PASS)

    parts = rate_text.split()
    try:
        cost_per_hour, currency = float(parts[0]), parts[1]
    except (IndexError, ValueError):
        report.add(
            "teardown.declared_rate_readable",
            FAIL,
            f"declared cost_per_vehicle_hour {rate_text!r} is not '<rate> <currency>', "
            "so the money figures cannot be re-derived and are not assumed correct",
        )
        return
    report.add("teardown.declared_rate_readable", PASS)

    deadhead_hours = total_deadhead / 60.0
    value = deadhead_hours * cost_per_hour
    _number(report, "teardown.deadhead_hours", figures.get("deadhead_hours"), deadhead_hours)
    _number(report, "teardown.value_at_full_cost", figures.get("value_at_full_cost"), value)
    report.ok(
        "teardown.currency",
        figures.get("currency") == currency,
        f"claimed currency {figures.get('currency')!r}, declared {currency!r}",
    )

    reduction_text = declared.get("reduction_fraction")
    share_text = declared.get("avoidable_share_of_cost_per_hour", "")
    share_parts = share_text.split("..")
    share = None
    if len(share_parts) == 2:
        try:
            share = (float(share_parts[0].strip()), float(share_parts[1].strip()))
        except ValueError:
            share = None

    if share is None or reduction_text is None:
        report.ok(
            "teardown.envelope_has_a_declared_basis",
            not claims_envelope,
            "a modelled envelope is claimed but the manifest declares no usable "
            "avoidable-share / reduction-fraction input to re-derive it from",
        )
        return
    report.add("teardown.envelope_has_a_declared_basis", PASS)

    try:
        reduction = float(reduction_text)
    except ValueError:
        report.add(
            "teardown.envelope_rederived",
            FAIL,
            f"declared reduction_fraction {reduction_text!r} is not a number",
        )
        return
    _number(
        report, "teardown.modelled_envelope_low",
        figures.get("modelled_envelope_low"), value * reduction * share[0],
    )
    _number(
        report, "teardown.modelled_envelope_high",
        figures.get("modelled_envelope_high"), value * reduction * share[1],
    )


def _number(report: Report, check_id: str, claimed: object, rederived: float | None) -> None:
    """Compare a claimed figure against one re-derived from the data. "Absent"
    and "present" are a real disagreement: a figure that should not exist (no
    denominator, no cost basis) is not a zero."""
    if (claimed is None) != (rederived is None):
        report.add(
            check_id, FAIL, f"claimed {claimed!r}, re-derived {rederived!r}"
        )
        return
    if claimed is None or rederived is None:
        report.add(check_id, PASS)
        return
    if not isinstance(claimed, (int, float)) or isinstance(claimed, bool):
        report.add(check_id, FAIL, f"claimed {claimed!r} is not a number")
        return
    report.ok(
        check_id,
        _close(float(claimed), rederived),
        f"claimed {claimed!r}, re-derived {rederived!r} from the embedded segments "
        "and the manifest's declared inputs",
    )


def _check_buckets(
    report: Report, label: str, claimed: list, rederived: dict, total_deadhead: float
) -> None:
    claimed_keys = sorted(str((b.get("day_of_week"), b.get("hour_of_day"))) for b in claimed)
    report.ok(
        f"teardown.{label}.buckets",
        claimed_keys == sorted(str(k) for k in rederived),
        "the claimed clock positions are not the ones the segments produce",
    )
    problems: list[str] = []
    for bucket in claimed:
        key = (bucket.get("day_of_week"), bucket.get("hour_of_day"))
        sums = rederived.get(key)
        if sums is None:
            problems.append(f"{key}: claimed a bucket the segments produce no minutes for")
            continue
        for name, claimed_value, rederived_value in (
            ("deadhead_minutes", bucket.get("deadhead_minutes"), sums["deadhead"]),
            ("revenue_minutes", bucket.get("revenue_minutes"), sums["revenue"]),
            (
                "deadhead_share_of_bucket",
                bucket.get("deadhead_share_of_bucket"),
                _share(sums["deadhead"], sums["deadhead"] + sums["revenue"]),
            ),
            (
                "share_of_total_deadhead",
                bucket.get("share_of_total_deadhead"),
                _share(sums["deadhead"], total_deadhead),
            ),
        ):
            if (claimed_value is None) != (rederived_value is None):
                problems.append(f"{key}.{name}: claimed {claimed_value!r}, re-derived {rederived_value!r}")
            elif claimed_value is not None and not _close(float(claimed_value), rederived_value):
                problems.append(f"{key}.{name}: claimed {claimed_value!r}, re-derived {rederived_value!r}")
    report.ok(f"teardown.{label}.minutes", not problems, "; ".join(problems))


def _check_runs(report: Report, teardown: dict, segments: list, total_deadhead: float) -> None:
    totals: dict = {}
    for row in segments:
        entry = totals.setdefault(
            row.get("run_ref"), {"revenue": 0.0, "deadhead": 0.0, "segments": 0}
        )
        minutes = _minutes(row)
        entry[row.get("kind")] = entry.get(row.get("kind"), 0.0) + (minutes or 0.0)
        entry["segments"] += 1

    ranked = sorted(
        (
            (run_ref, sums)
            for run_ref, sums in totals.items()
            if run_ref is not None and sums["deadhead"] > 0
        ),
        key=lambda item: (-round(item[1]["deadhead"], 6), item[0]),
    )
    report.ok(
        "teardown.attributed_run_count",
        teardown.get("attributed_run_count") == len(ranked),
        f"claimed {teardown.get('attributed_run_count')!r} attributed runs, "
        f"re-derived {len(ranked)}",
    )
    top = teardown.get("top_runs") or []
    report.ok(
        "teardown.top_runs_order",
        [r.get("run_ref") for r in top] == [run_ref for run_ref, _ in ranked[: len(top)]],
        "the claimed run ranking is not the one the segments produce",
    )

    problems: list[str] = []
    rows = list(top)
    unattributable = teardown.get("unattributable")
    report.ok(
        "teardown.unattributable_presence",
        (unattributable is not None) == (None in totals),
        "the pack disagrees with the segments about whether any segment was "
        "carried without a run identifier",
    )
    if isinstance(unattributable, dict) and None in totals:
        rows.append(unattributable)
    for row in rows:
        sums = totals.get(row.get("run_ref"))
        if sums is None:
            problems.append(f"claimed run {row.get('run_ref')!r} has no segments")
            continue
        for name, claimed, rederived in (
            ("deadhead_minutes", row.get("deadhead_minutes"), sums["deadhead"]),
            ("revenue_minutes", row.get("revenue_minutes"), sums["revenue"]),
            ("segment_count", row.get("segment_count"), float(sums["segments"])),
            (
                "share_of_total_deadhead",
                row.get("share_of_total_deadhead"),
                _share(sums["deadhead"], total_deadhead),
            ),
        ):
            if (claimed is None) != (rederived is None):
                problems.append(f"run {row.get('run_ref')!r}.{name}: claimed {claimed!r}, re-derived {rederived!r}")
            elif claimed is not None and not _close(float(claimed), rederived):
                problems.append(f"run {row.get('run_ref')!r}.{name}: claimed {claimed!r}, re-derived {rederived!r}")
    report.ok("teardown.run_contributions", not problems, "; ".join(problems))


def check_teardown(pack: dict, report: Report) -> None:
    """Recompute a carried teardown's headline figures from two sources only:
    the embedded segments, and the manifest's declared `(name, value, source)`
    inputs. A claimed figure is never an input to its own check."""
    manifest = pack.get("manifest") or {}
    teardown = pack.get("teardown")

    if teardown is None:
        report.ok(
            "teardown.declared_presence",
            not manifest.get("teardown_included"),
            "the manifest claims a teardown is included, but the pack carries none",
        )
        report.add("teardown.figures_rederived", NOT_APPLICABLE, "no teardown carried")
        return

    segments = teardown.get("segments") or []
    report.ok(
        "teardown.declared_presence",
        bool(manifest.get("teardown_included")),
        "the pack carries a teardown its manifest does not declare",
    )
    report.ok(
        "teardown.manifest_summary",
        (
            manifest.get("teardown_id") == teardown.get("teardown_id")
            and manifest.get("teardown_data_provenance") == teardown.get("data_provenance")
            and manifest.get("teardown_segment_count") == len(segments)
        ),
        "the pack manifest's summary of the teardown disagrees with the teardown "
        "it carries",
    )
    report.ok(
        "teardown.never_claims_causation",
        teardown.get("causal_proof") is False
        and (teardown.get("figures") or {}).get("is_guaranteed_saving") is not True,
        "a teardown in an evidence pack claims causal proof or a guaranteed "
        "saving; both are refused",
    )

    bad_kinds = sorted({str(s.get("kind")) for s in segments if s.get("kind") not in _SEGMENT_KINDS})
    if bad_kinds:
        report.add(
            "teardown.figures_rederived",
            FAIL,
            f"segments carry unknown kinds {bad_kinds}, so nothing can be re-derived",
        )
        return

    inner = teardown.get("manifest") or {}
    declared = _declared_inputs(inner)
    report.ok(
        "teardown.self_description",
        (
            teardown.get("teardown_id") == inner.get("teardown_id")
            and teardown.get("data_provenance") == inner.get("data_provenance")
            and inner.get("segment_count") == len(segments)
        ),
        "the teardown's own fields disagree with the manifest record it carries",
    )

    total_deadhead = sum(
        (_minutes(s) or 0.0) for s in segments if s.get("kind") == "deadhead"
    )
    total_revenue = sum(
        (_minutes(s) or 0.0) for s in segments if s.get("kind") == "revenue"
    )
    figures = teardown.get("figures") or {}
    _number(report, "teardown.total_deadhead_minutes", figures.get("total_deadhead_minutes"), total_deadhead)
    _number(report, "teardown.total_revenue_minutes", figures.get("total_revenue_minutes"), total_revenue)
    _number(
        report,
        "teardown.deadhead_share_of_vehicle_time",
        figures.get("deadhead_share_of_vehicle_time"),
        _share(total_deadhead, total_deadhead + total_revenue),
    )

    by_hour: dict = {}
    by_day: dict = {}
    for segment in segments:
        start, end = _instant(segment.get("started_at")), _instant(segment.get("ended_at"))
        if start is None or end is None:
            continue
        for hour_start, minutes in _hour_slices(start, end):
            for table, key in (
                (by_hour, (None, hour_start.hour)),
                (by_day, (hour_start.weekday(), None)),
            ):
                sums = table.setdefault(key, {"revenue": 0.0, "deadhead": 0.0})
                sums[segment.get("kind")] = sums.get(segment.get("kind"), 0.0) + minutes

    _check_buckets(report, "by_hour_of_day", teardown.get("by_hour_of_day") or [], by_hour, total_deadhead)
    _check_buckets(report, "by_day_of_week", teardown.get("by_day_of_week") or [], by_day, total_deadhead)

    if teardown.get("run_refs_redacted"):
        report.add(
            "teardown.run_contributions",
            NOT_CHECKABLE,
            "run identifiers are redacted, so no segment can be matched to the "
            "run it is claimed under",
        )
    else:
        _check_runs(report, teardown, segments, total_deadhead)

    _check_teardown_cost(figures, declared, total_deadhead, report)

    if teardown.get("run_refs_redacted"):
        report.add(
            "teardown.segment_fingerprint",
            NOT_CHECKABLE,
            "masking run identifiers changes the bytes the manifest's "
            "segment_sha256 was computed over, so this pack cannot prove its "
            "segments are the ones the teardown ran on",
        )
    else:
        recomputed = segment_fingerprint(segments)
        report.ok(
            "teardown.segment_fingerprint",
            recomputed == inner.get("segment_sha256"),
            f"manifest says {inner.get('segment_sha256')}, re-derived {recomputed} "
            "from the embedded segments (these are not the segments this teardown "
            "was computed from)",
        )


# --------------------------------------------------------------------------- #
# Entry points                                                                 #
# --------------------------------------------------------------------------- #


def verify_pack(pack: dict, report: Report | None = None) -> Report:
    """Verify a bare `EvidencePack` document (the `pack` member of a pack file)."""
    report = report or Report()
    if not isinstance(pack, dict) or "manifest" not in pack:
        report.add("pack.shape", FAIL, "this document is not an evidence pack")
        return report
    report.add("pack.shape", PASS)

    manifest = pack.get("manifest") or {}
    recomputed = bundle_hash(
        pack.get("evidence"), pack.get("raw_events") or [], pack.get("outcome"), pack.get("teardown")
    )
    report.ok(
        "pack.bundle_checksum",
        recomputed == manifest.get("bundle_sha256"),
        f"manifest says {manifest.get('bundle_sha256')}, recomputed {recomputed} "
        "(pack content was altered after export)",
    )

    _check_manifest(pack, report)
    _check_narrative_against_ledger(pack, report)
    _check_redaction(pack, report)
    check_teardown(pack, report)

    if manifest.get("independently_verifiable"):
        _check_chain(pack, report)
    else:
        report.add(
            "chain.rehashed",
            NOT_CHECKABLE,
            "this pack is marked non-independently-verifiable (redacted): the "
            "per-event hashes were computed over the ORIGINAL payloads, so a "
            "masked pack cannot chain-reverify by design",
        )
    return report


def verify_pack_file(document: dict) -> Report:
    """Verify a pack file: the attestation, the embedded verifier's digest, the
    file checksum, and then the pack itself."""
    report = Report()
    if not isinstance(document, dict):
        report.add("file.shape", FAIL, "the document is not a JSON object")
        return report

    if "pack_file_version" not in document and "manifest" in document:
        # A bare pack, handed over without the file envelope. Verify what is
        # there and say plainly that the scope declaration is missing.
        report.add(
            "file.shape",
            NOT_APPLICABLE,
            "this is a bare evidence pack, not a pack file: no attestation and no "
            "embedded verifier to check",
        )
        return verify_pack(document, report)

    report.add("file.shape", PASS)

    verifier = document.get("verifier") or {}
    source = verifier.get("source")
    if isinstance(source, str):
        report.ok(
            "file.verifier_digest",
            sha256_hex(source) == verifier.get("sha256"),
            "the embedded verifier's recorded sha256 does not match its own "
            "source text",
        )
    else:
        report.add("file.verifier_digest", FAIL, "the pack file embeds no verifier source")

    body = {
        "attestation": document.get("attestation"),
        "algorithm": document.get("algorithm"),
        "pack": document.get("pack"),
        "verifier": verifier,
    }
    recomputed = sha256_hex(canonical_json(body))
    report.ok(
        "file.checksum",
        recomputed == document.get("file_sha256"),
        f"file says {document.get('file_sha256')}, recomputed {recomputed} "
        "(the pack file was altered after it was written)",
    )

    check_attestation(document.get("attestation"), report)
    return verify_pack(document.get("pack") or {}, report)


_SELF_CHECK_CAVEAT = (
    "NOTE: this script recomputes its own embedded digest, which cannot detect a "
    "tampered script -- the same code would be doing the checking. Compare "
    "verifier.sha256 against a copy obtained from the issuer separately, or read "
    "this script; `algorithm` in the pack file states every rule needed to "
    "reimplement it independently."
)


def render(report: Report) -> str:
    lines = [f"milexium pack verifier {VERIFIER_VERSION}", ""]
    for check in report.checks:
        mark = {PASS: "PASS", FAIL: "FAIL", NOT_APPLICABLE: "n/a ", NOT_CHECKABLE: "SKIP"}[
            check.status
        ]
        lines.append(f"  [{mark}] {check.check_id}" + (f" -- {check.detail}" if check.detail else ""))
    lines.append("")
    lines.append("VERIFIED" if report.verified else "NOT VERIFIED")
    if report.unavailable:
        lines.append(
            "  checks skipped by declared design (never counted as passing): "
            + ", ".join(c.check_id for c in report.unavailable)
        )
    lines.append("")
    lines.append(_SELF_CHECK_CAVEAT)
    return "\n".join(lines)


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=VERIFIER_FILENAME,
        description=(
            "Verify a Milexium evidence pack file with no Milexium code installed. "
            "Exit 0 = every check passed; 1 = something failed or could not be "
            "checked; 2 = the file could not be read."
        ),
    )
    parser.add_argument("path", help="path to the pack file (JSON)")
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = parser.parse_args(argv)

    try:
        with open(args.path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        sys.stderr.write(f"cannot read {args.path}: {error}\n")
        return 2

    report = verify_pack_file(document)
    sys.stdout.write(
        (json.dumps(report.as_dict(), indent=2, sort_keys=True) if args.json else render(report))
        + "\n"
    )
    return 0 if report.verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
