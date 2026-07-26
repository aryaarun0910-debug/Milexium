"""The artifact that actually leaves the building: a pack file a third party can
check without us.

`aletheia/evidence/export.py` produces an `EvidencePack` and calls it
"independently verifiable". It is re-derivable in principle -- every claim is
recomputed from the primitive records the pack carries -- but the only thing
that could do the recomputing was `verify_evidence_pack`, which imports
`themis.canonical`, `aletheia.verify` and Pydantic. A reviewer holding the
pack still had to install and run Milexium's code to check Milexium's claim.
That is a report with extra steps.

A `VerifiablePackFile` closes that. It carries three things beyond the pack:

1. **The verifier itself**, as source text
   (`aletheia/evidence/standalone_verifier.py`, which imports nothing from this
   repository). Write it to a file and run it on a stock CPython:
   `python verify_milexium_pack.py pack.json`. Nothing to install.
2. **The algorithm**, as machine-readable rules, so the script is a convenience
   and not the only path -- a third party who (rightly) will not run a script
   the subject supplied can reimplement the checks in any language from
   `algorithm` alone. This is the path that makes the claim honest, because a
   script the issuer wrote cannot vouch for the issuer.
3. **An attestation scope**, as fields rather than prose: what this artifact
   asserts, and -- structurally, with `False` enforced by validators that refuse
   the dishonest value -- what it does not. This repository holds no consented
   operator data, so a pack can attest *"this computation follows from these
   inputs"* and never *"this reflects operational reality"*. The verifier FAILS
   a pack file that overclaims, so the limit is checked rather than merely
   written down.

**Why this is a new model rather than fields on `PackManifest`.** `PackManifest`
and `EvidencePack` are exported into `talos/contracts/openapi/milexium-api-v0.1.json`,
which a CI drift check holds byte-identical and which this packet does not own
(the same constraint ADR-0045 recorded). The envelope therefore wraps the pack
and carries it verbatim as a dict; already-issued packs and their checksums are
untouched, and the contract layer stays exactly as it was.

Status: **Demonstrated**. Nothing here is Validated -- no consented operator
data exists to validate against, and `AttestationScope` refuses to say otherwise.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from aletheia.evidence.export import EvidencePack
from aletheia.evidence.standalone_verifier import (
    VERIFIER_FILENAME,
    VERIFIER_VERSION,
    canonical_json,
)
from aletheia.evidence.standalone_verifier import verify_pack_file as _run_verifier

PACK_FILE_VERSION = "0.1.0"

VERIFIER_INVOCATION = f"python {VERIFIER_FILENAME} <this-file>.json"

_VERIFIER_PATH = Path(__file__).with_name("standalone_verifier.py")


DataProvenance = Literal["real_public", "synthetic", "mixed"]
"""Mirrors ADR-0039's provenance vocabulary, including the deliberate absence of
an "operator" value, widened only by "mixed" for a pack whose ledger and
teardown came from different public/synthetic sources. There is no value here
that claims consented operator data, because there is none."""

PackStatus = Literal["Exists", "Specified", "Demonstrated"]
"""The repository's status vocabulary, truncated at Demonstrated on purpose:
"Validated" requires consented operator data and none exists, so it is not a
value this artifact can hold."""


# --------------------------------------------------------------------------- #
# What the artifact does and does not assert                                    #
# --------------------------------------------------------------------------- #

ATTESTS: tuple[str, ...] = (
    "bytes_unaltered_since_export",
    "hash_chain_recomputes_from_the_carried_ledger_rows",
    "narrative_follows_from_the_carried_ledger_rows",
    "manifest_summarizes_its_own_body_truthfully",
    "declared_redaction_was_actually_performed",
    "teardown_figures_follow_from_the_carried_segments_and_declared_inputs",
)
"""Every claim key the embedded verifier actually re-derives. Each maps onto a
check id in `standalone_verifier`, so the list is not decoration -- a claim with
no check behind it would be exactly the "restated, not re-derived" failure this
packet exists to close."""

DOES_NOT_ATTEST: tuple[str, ...] = (
    "reflects_operational_reality",
    "the_carried_inputs_describe_a_real_operation",
    "the_records_included_were_not_selected_by_the_issuer",
    "any_empty_time_was_avoidable",
    "any_money_would_be_recovered",
    "a_causal_relationship_between_any_decision_and_any_outcome",
    "de_identification_of_any_person",
    "compliance_with_hipaa_soc2_iso_or_ada",
    "the_embedded_verifier_is_the_one_the_issuer_published",
)
"""The limits, as keys rather than paragraphs.

Two of these are easy to skip past and are the most important. *The records
included were not selected by the issuer*: a pack proves its own internal
consistency perfectly and says nothing about what was left out of it -- a
flattering subset verifies exactly as well as a complete one. *The embedded
verifier is the one the issuer published*: a tampered file could carry a
tampered script that reports success, so the digest this file recomputes for
itself proves nothing on its own; `algorithm` exists so the check does not
depend on the script at all."""


class AttestationScope(BaseModel):
    """The machine-readable scope of what this artifact claims.

    The three refusals below are validators, not defaults, for the same reason
    `TeardownFigures.is_guaranteed_saving` and `TeardownEvidence.causal_proof`
    are: the artifact is what a partner reads, so the boundary is enforced where
    it can actually be violated. A caller cannot construct an overclaiming pack
    file even by accident, and the standalone verifier re-checks the same
    conditions on the recipient's desk -- because a validator that only runs in
    our process protects nobody holding the file.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: PackStatus = "Demonstrated"
    data_provenance: DataProvenance
    attests: tuple[str, ...] = ATTESTS
    does_not_attest: tuple[str, ...] = DOES_NOT_ATTEST

    computation_follows_from_inputs: bool = True
    """The one positive claim: every figure in this artifact is recomputable
    from the primitive records carried with it. This is arithmetic, and it is
    the whole of what verification establishes."""

    reflects_operational_reality: bool = False
    consented_operator_input: bool = False
    operator_data_present: bool = False
    causal_claim: bool = False

    note: str

    @field_validator(
        "reflects_operational_reality",
        "consented_operator_input",
        "operator_data_present",
        "causal_claim",
    )
    @classmethod
    def _refused(cls, value: bool, info) -> bool:
        if value:
            raise ValueError(
                f"{info.field_name} may never be True in a Milexium evidence pack "
                "file: this repository holds no consented operator data, so an "
                "artifact leaving it cannot assert operational reality, operator "
                "input, or causation. The pack attests that its computation "
                "follows from the inputs it carries, and nothing beyond that."
            )
        return value

    @field_validator("computation_follows_from_inputs")
    @classmethod
    def _the_one_claim_must_be_made(cls, value: bool) -> bool:
        if not value:
            raise ValueError(
                "computation_follows_from_inputs is the only claim a pack file "
                "makes; a pack file that withholds it is not an evidence pack"
            )
        return value

    @field_validator("does_not_attest")
    @classmethod
    def _limits_must_be_stated(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        missing = [key for key in DOES_NOT_ATTEST if key not in value]
        if missing:
            raise ValueError(
                "an evidence pack file must carry every declared limit; missing "
                f"{missing}. Limits are carried verbatim, never trimmed for the "
                "reader, exactly as the teardown's hedges are."
            )
        return value


_ATTESTATION_NOTE = (
    "This artifact attests that its recorded figures follow from the primitive "
    "records carried inside it -- nothing more. It is built from public and/or "
    "synthetic data with NO consented operator input, so it cannot and does not "
    "attest that those records describe a real operation, that the selection of "
    "records was complete, or that any decision caused any outcome. "
    "Tamper-evident, not immutable, and not a compliance certificate."
)


# --------------------------------------------------------------------------- #
# The algorithm, stated so the script is not the only path                      #
# --------------------------------------------------------------------------- #


class AlgorithmRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str
    rule: str


ALGORITHM: tuple[AlgorithmRule, ...] = (
    AlgorithmRule(
        rule_id="canonical_json",
        rule=(
            "Every hash below is sha256 over the UTF-8 bytes of a canonical JSON "
            "serialization: object keys sorted ascending by code point, separators "
            "',' and ':' with no whitespace, non-ASCII escaped (Python: "
            "json.dumps(x, sort_keys=True, separators=(',',':'), ensure_ascii=True))."
        ),
    ),
    AlgorithmRule(
        rule_id="file_sha256",
        rule=(
            "file_sha256 = sha256(canonical_json({'attestation': ..., 'algorithm': "
            "..., 'pack': ..., 'verifier': ...})) over this file's own members of "
            "those names. file_sha256 itself and pack_file_version/note are outside "
            "the hash."
        ),
    ),
    AlgorithmRule(
        rule_id="verifier_sha256",
        rule=(
            "verifier.sha256 = sha256(verifier.source encoded UTF-8). This is a "
            "convenience only: a tampered file can carry a matching tampered "
            "script. Obtain the digest from the issuer separately, or reimplement "
            "these rules and ignore the script."
        ),
    ),
    AlgorithmRule(
        rule_id="pack.bundle_sha256",
        rule=(
            "pack.manifest.bundle_sha256 = sha256(canonical_json({'evidence': "
            "pack.evidence, 'raw_events': pack.raw_events, 'outcome': "
            "pack.outcome})), with the key 'teardown': pack.teardown added ONLY "
            "when a teardown is carried. The manifest is excluded -- it is where "
            "the checksum lives -- so every other manifest field must be "
            "re-derived from the body (see manifest.rederived)."
        ),
    ),
    AlgorithmRule(
        rule_id="event_hash",
        rule=(
            "For each row in pack.raw_events: hash = sha256 of the concatenation, "
            "in this order, of prev_hash ('' when null), canonical_json of "
            "json.loads(payload_json), str(sequence), aggregate_id, and "
            "idempotency_key ('' when null) -- each UTF-8 encoded. Rows sorted by "
            "sequence must start at 1, increase by 1, and each row's prev_hash "
            "must equal the previous row's hash."
        ),
    ),
    AlgorithmRule(
        rule_id="manifest.rederived",
        rule=(
            "manifest.event_count = len(pack.raw_events); manifest.aggregate_id = "
            "pack.evidence.aggregate_id and equals every row's aggregate_id; "
            "manifest.tenant_id = pack.evidence.tenant_id; "
            "manifest.integrity_verified_at_export = "
            "pack.evidence.integrity_verified, which itself must equal (no "
            "chain_violations and no schema_violations and (not "
            "state_check_applicable or no state_violations))."
        ),
    ),
    AlgorithmRule(
        rule_id="narrative.rederived",
        rule=(
            "Every event record embedded in pack.evidence (known_inputs, proposed, "
            "approved_or_overridden, outcome_events, executed) must match the "
            "pack.raw_events row with the same event_id on every field it carries: "
            "payload against json.loads(payload_json), reason_codes against "
            "json.loads(reason_codes), occurred_at compared as an instant (the two "
            "places spell UTC as '+00:00' and 'Z'), and everything else by "
            "equality. pack.outcome must equal pack.evidence.observed. occurred_at "
            "is NOT an input to event_hash, so this is the only check that sees an "
            "edit to it."
        ),
    ),
    AlgorithmRule(
        rule_id="redaction.rederived",
        rule=(
            "For each bare key name in manifest.redacted_fields (entries "
            "containing '.' or '[' are structural teardown paths, not payload "
            "keys), walk pack.evidence, pack.outcome and every "
            "json.loads(payload_json) at any depth: the key must hold exactly the "
            "string '[REDACTED]' wherever it appears. A pack claiming a redaction "
            "it did not perform fails."
        ),
    ),
    AlgorithmRule(
        rule_id="teardown.segment_sha256",
        rule=(
            "Build [started_at, ended_at, kind, run_ref] for each segment, sort "
            "those lists by (started_at, ended_at, kind, run_ref or ''), then "
            "sha256(canonical_json({'segments': sorted})). Not checkable when "
            "run_refs_redacted is true -- masking changes the bytes it covers."
        ),
    ),
    AlgorithmRule(
        rule_id="teardown.figures",
        rule=(
            "Segment minutes = (ended_at - started_at) in minutes. "
            "total_deadhead_minutes / total_revenue_minutes are the sums by kind; "
            "deadhead_share_of_vehicle_time = deadhead/(deadhead+revenue) or null "
            "when the denominator is 0. Buckets: split each segment at hour "
            "boundaries and add each slice to hour-of-day and day-of-week "
            "(weekday(), Monday=0) tables. Runs: group whole segments by run_ref, "
            "rank by deadhead minutes descending then run_ref ascending. Money: "
            "deadhead_hours = total_deadhead_minutes/60; value_at_full_cost = "
            "deadhead_hours * the rate parsed from the declared "
            "cost_per_vehicle_hour input ('<rate> <currency>'); envelope = "
            "value_at_full_cost * declared reduction_fraction * each end of the "
            "declared avoidable_share_of_cost_per_hour ('<low> .. <high>'). Every "
            "input comes from teardown.manifest.inputs (name, value, source) and "
            "NEVER from the figures being checked."
        ),
    ),
    AlgorithmRule(
        rule_id="tolerance",
        rule=(
            "Figures are emitted rounded to 6 decimal places, so compare with "
            "abs(claimed - rederived) <= 1e-6 + abs(rederived) * 1e-9. Any byte "
            "change smaller than that is still caught by bundle_sha256."
        ),
    ),
    AlgorithmRule(
        rule_id="verdict",
        rule=(
            "The artifact is verified only when no check failed AND no check was "
            "skipped by design. A redacted pack cannot chain-reverify (the "
            "per-event hashes cover the ORIGINAL payloads), so it is reported as "
            "not verified with the reason stated -- never as passed."
        ),
    ),
    AlgorithmRule(
        rule_id="attestation",
        rule=(
            "attestation.reflects_operational_reality, consented_operator_input, "
            "operator_data_present and causal_claim must each be present and "
            "false; status must not be 'Validated' or 'Production'; "
            "data_provenance must be one of real_public / synthetic / mixed (there "
            "is no operator provenance); does_not_attest must be non-empty. A pack "
            "file that overclaims fails verification."
        ),
    ),
)


# --------------------------------------------------------------------------- #
# The file                                                                      #
# --------------------------------------------------------------------------- #


class EmbeddedVerifier(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    filename: str
    language: str
    version: str
    requires: str
    invocation: str
    sha256: str
    source: str


class VerifiablePackFile(BaseModel):
    """An `EvidencePack` plus everything needed to check it without us."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pack_file_version: str
    attestation: AttestationScope
    algorithm: tuple[AlgorithmRule, ...]
    pack: dict
    """The `EvidencePack` dumped verbatim. Carried as a dict, not as the model,
    so the contract-exported pack shape is untouched by this envelope."""
    verifier: EmbeddedVerifier
    file_sha256: str
    note: str

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "VerifiablePackFile":
        return cls.model_validate(json.loads(text))


_FILE_NOTE = (
    "Self-contained evidence pack file. `verifier.source` is a complete Python "
    "script that imports nothing from Milexium; write it to a file and run "
    f"`{VERIFIER_INVOCATION}` on a stock CPython to check this artifact. Because "
    "a script supplied by the subject of an audit is worth little on its own, "
    "`algorithm` states every normative rule needed to reimplement the checks "
    "independently in any language -- that is the path that makes the "
    "verification genuinely third-party. `attestation` states, as fields, what "
    "this artifact does and does not claim."
)


def verifier_source() -> str:
    """The embedded verifier's source, read deterministically.

    Two things make the digest a property of the algorithm rather than of the
    checkout that produced the file -- a pack file built on Windows and one
    built on Linux must be byte-identical or determinism is a claim rather than
    a fact. First, line endings: `read_text` decodes in universal-newline mode,
    so a CRLF checkout arrives as `\\n` here without any help from this
    function. Second, the encoding: that one is NOT free, so a non-ASCII byte is
    refused rather than embedded, because its bytes would depend on the encoding
    the reading side happened to choose.
    """
    text = _VERIFIER_PATH.read_text(encoding="utf-8")
    if not text.isascii():
        raise ValueError(
            "the standalone verifier's source is not pure ASCII; a non-ASCII byte "
            "would make the embedded digest depend on the encoding a checkout "
            "happened to use, which is exactly the non-determinism a verifiable "
            "artifact cannot carry"
        )
    return text


def _file_hash(
    attestation: AttestationScope,
    algorithm: tuple[AlgorithmRule, ...],
    pack: dict,
    verifier: EmbeddedVerifier,
) -> str:
    body = {
        "attestation": attestation.model_dump(mode="json"),
        "algorithm": [rule.model_dump(mode="json") for rule in algorithm],
        "pack": pack,
        "verifier": verifier.model_dump(mode="json"),
    }
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def build_pack_file(
    pack: EvidencePack, *, data_provenance: DataProvenance
) -> VerifiablePackFile:
    """Wrap an `EvidencePack` into the artifact a third party actually receives.

    `data_provenance` is required and has no default: a pack file that guessed
    where its data came from would be making exactly the kind of unearned claim
    the attestation exists to prevent. If the pack carries a teardown, the
    declared provenance must agree with the teardown's own, or say "mixed" --
    a disagreement is refused rather than quietly resolved.
    """
    dump = pack.model_dump(mode="json")

    teardown = dump.get("teardown")
    if teardown is not None:
        carried = teardown.get("data_provenance")
        if data_provenance != carried and data_provenance != "mixed":
            raise ValueError(
                f"declared data_provenance {data_provenance!r} disagrees with the "
                f"carried teardown's {carried!r}; declare 'mixed' if the pack "
                "genuinely draws on both, but do not overwrite the teardown's own "
                "record of where its data came from"
            )

    source = verifier_source()
    verifier = EmbeddedVerifier(
        filename=VERIFIER_FILENAME,
        language="python",
        version=VERIFIER_VERSION,
        requires="CPython 3.11+ standard library only; no third-party packages",
        invocation=VERIFIER_INVOCATION,
        sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
        source=source,
    )
    attestation = AttestationScope(
        data_provenance=data_provenance,
        note=_ATTESTATION_NOTE,
    )
    return VerifiablePackFile(
        pack_file_version=PACK_FILE_VERSION,
        attestation=attestation,
        algorithm=ALGORITHM,
        pack=dump,
        verifier=verifier,
        file_sha256=_file_hash(attestation, ALGORITHM, dump, verifier),
        note=_FILE_NOTE,
    )


def write_verifier_script(document: dict, directory: Path) -> Path:
    """Extract the embedded verifier to `directory` -- the first step of the
    recipient's workflow, and the one that must not require our code. Written
    with `newline="\\n"` so the digest holds on any platform."""
    path = Path(directory) / document["verifier"]["filename"]
    path.write_text(document["verifier"]["source"], encoding="utf-8", newline="\n")
    return path


def verify_pack_file_document(document: dict) -> dict:
    """Run the SAME code the recipient runs, and return its report.

    This deliberately delegates to `standalone_verifier` rather than
    re-implementing the checks: if the in-repo path and the shipped script could
    drift, the shipped script would be the one nobody tested.
    """
    return _run_verifier(document).as_dict()
