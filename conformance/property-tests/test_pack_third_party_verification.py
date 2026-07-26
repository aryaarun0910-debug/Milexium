"""Can a third party check this pack without us? -- MX-I-THIRD-PARTY-VERIFY-010.

ADR-0017 called the evidence pack "independently verifiable". It was
re-derivable, but the only thing that could re-derive it was
`verify_evidence_pack`, which imports `packages.canonical`, `packages.verify`
and Pydantic. "Independent" meant "install our code and run our verifier". These
tests hold the stronger claim to account:

- the verifier that ships inside the pack imports **nothing** from this
  repository -- asserted against its AST, not its docstring;
- it is **extracted from the pack file and executed in a separate interpreter**,
  with a control test proving Milexium is genuinely unimportable in that
  interpreter, so a passing verification cannot have been produced by our code;
- **every tamper case fails**: a payload value, a stored hash, a manifest claim,
  a timestamp, a teardown figure, a redaction that was claimed but not
  performed, an attestation that overclaims, and a swapped verifier script. The
  load-bearing ones re-anchor BOTH checksums first, so the attacker wins every
  hash and re-derivation catches them anyway. A verifier that passes everything
  proves nothing;
- the artifact is **byte-deterministic**: two of these tests are regressions for
  non-determinism found while writing them (raw-row order and redaction-key
  order both changed the pack's bytes and checksum for identical facts);
- the pack is **structurally honest about what it cannot prove** -- the scope is
  a set of machine-readable fields with validators that refuse the dishonest
  value, and the standalone verifier FAILS a pack file that overclaims.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from packages.canonical import DecisionEventType, SqliteCanonicalStore
from packages.evidence import pack_file
from packages.evidence import standalone_verifier as sv
from packages.evidence import (
    DOES_NOT_ATTEST,
    AttestationScope,
    EvidencePack,
    build_evidence_pack,
    build_pack_file,
    capture_teardown,
    redact_pack,
    verifier_source,
    verify_evidence_pack,
    verify_pack_file_document,
    write_verifier_script,
)
from packages.replay import CostBasis, VehicleSegment, teardown_deadhead

from conformance.fixtures.builders import example_tenant

_VERIFIER_PATH = Path(sv.__file__)
MONDAY = datetime(2026, 7, 20, tzinfo=timezone.utc)
SENSITIVE = "prefers front seat"


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


def _seeded_chain() -> tuple[SqliteCanonicalStore, str, str]:
    store = SqliteCanonicalStore()
    tenant = example_tenant()
    store.create_tenant(tenant)
    aggregate_id = "req-thirdparty-0001"
    store.append_event(
        tenant_id=tenant.tenant_id, aggregate_id=aggregate_id,
        aggregate_type="ServiceRequest", occurred_at=_utc(2026, 7, 23, 8, 0),
        actor_type="system", actor_id="scheduler",
        event_type=DecisionEventType.RECOMMENDATION,
        payload={"assignment": "vehicle-7"},
    )
    store.append_event(
        tenant_id=tenant.tenant_id, aggregate_id=aggregate_id,
        aggregate_type="ServiceRequest", occurred_at=_utc(2026, 7, 23, 9, 0),
        actor_type="human", actor_id="dispatcher-2",
        event_type=DecisionEventType.OVERRIDE,
        payload={"assignment": "vehicle-3", "rider_note": SENSITIVE},
    )
    return store, tenant.tenant_id, aggregate_id


def _pack(**kwargs) -> EvidencePack:
    store, tenant_id, aggregate_id = _seeded_chain()
    return build_evidence_pack(
        store.history(tenant_id, aggregate_id),
        store.raw_rows_for_tenant(tenant_id),
        **kwargs,
    )


def _segment(*, day=0, hour=9, minute=0, minutes=30.0, kind="deadhead", run="RUN-A"):
    start = MONDAY + timedelta(days=day, hours=hour, minutes=minute)
    return VehicleSegment(
        started_at=start, ended_at=start + timedelta(minutes=minutes), kind=kind, run_ref=run
    )


def _teardown_evidence():
    """A small week with an hour-straddling segment, two runs, a second day, and
    one segment the export never identified a run for."""
    segments = (
        _segment(day=0, hour=9, minute=50, minutes=30.0, kind="deadhead", run="RUN-A"),
        _segment(day=0, hour=6, minutes=120.0, kind="revenue", run="RUN-A"),
        _segment(day=0, hour=22, minutes=45.0, kind="deadhead", run="RUN-B"),
        _segment(day=0, hour=12, minutes=200.0, kind="revenue", run="RUN-B"),
        _segment(day=2, hour=4, minutes=20.0, kind="deadhead", run="RUN-B"),
        _segment(day=2, hour=5, minutes=15.0, kind="deadhead", run=None),
        _segment(day=2, hour=7, minutes=90.0, kind="revenue", run=None),
    )
    torn = teardown_deadhead(
        segments,
        dataset_label="fixture-week",
        data_provenance="real_public",
        run_ref_source="run_ref (fixture)",
        cost_basis=CostBasis(
            cost_per_vehicle_hour=76.885,
            currency="USD",
            source="2024 NTD demand-response filings, national median (stand-in)",
            avoidable_share_low=0.2,
            avoidable_share_high=0.45,
        ),
    )
    return capture_teardown(torn, segments)


def _document(pack: EvidencePack | None = None, *, provenance="synthetic") -> dict:
    return json.loads(build_pack_file(pack or _pack(), data_provenance=provenance).to_json())


def _reanchor(document: dict) -> dict:
    """Recompute BOTH checksums the way a competent attacker would -- the
    algorithm is published, so an attacker who edits content and leaves the
    hashes stale is the easy case. These tests make them win the hashes."""
    pack = document["pack"]
    pack["manifest"]["bundle_sha256"] = sv.bundle_hash(
        pack["evidence"], pack["raw_events"], pack["outcome"], pack.get("teardown")
    )
    document["file_sha256"] = sv.sha256_hex(
        sv.canonical_json(
            {
                "attestation": document["attestation"],
                "algorithm": document["algorithm"],
                "pack": pack,
                "verifier": document["verifier"],
            }
        )
    )
    return document


def _verify(document: dict) -> dict:
    return verify_pack_file_document(document)


def _statuses(report: dict) -> dict:
    return {check["check_id"]: check["status"] for check in report["checks"]}


# --------------------------------------------------------------------------- #
# 1. The verifier owes this repository nothing                                  #
# --------------------------------------------------------------------------- #

_STDLIB_ONLY = {"argparse", "hashlib", "json", "sys", "dataclasses", "datetime", "__future__"}


def test_standalone_verifier_imports_nothing_from_this_repository() -> None:
    """Asserted against the AST, not the docstring. If this module ever imports
    `packages.*`, the pack becomes checkable only by us again -- which is the
    exact defect this packet exists to close, and it would be invisible: every
    other test here would still pass."""
    tree = ast.parse(_VERIFIER_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert imported <= _STDLIB_ONLY, (
        f"the standalone verifier imports {sorted(imported - _STDLIB_ONLY)}; it may "
        "use the Python standard library and nothing else"
    )
    # Belt and braces: no repository package by name, and no Pydantic.
    for forbidden in ("packages", "conformance", "demo", "pydantic"):
        assert forbidden not in imported


def test_embedded_verifier_source_is_the_file_on_disk_and_is_pure_ascii() -> None:
    document = _document()
    source = document["verifier"]["source"]

    assert source == verifier_source()
    assert sv.sha256_hex(source) == document["verifier"]["sha256"]
    assert source.isascii(), (
        "a non-ASCII byte would make the embedded digest depend on the encoding a "
        "checkout happened to use"
    )
    assert "\r" not in source


def test_a_non_ascii_verifier_source_is_refused_rather_than_silently_embedded(
    tmp_path, monkeypatch
) -> None:
    """The digest must be a property of the algorithm, not of the encoding the
    reading side happened to choose. Line endings normalize for free (universal
    newline decoding); the encoding does not, so it is a refusal."""
    impostor = tmp_path / "standalone_verifier.py"
    impostor.write_text('SIGN = "—"\n', encoding="utf-8")
    monkeypatch.setattr(pack_file, "_VERIFIER_PATH", impostor)

    with pytest.raises(ValueError, match="not pure ASCII"):
        pack_file.verifier_source()


def test_a_good_pack_verifies_in_an_interpreter_where_milexium_does_not_exist(tmp_path) -> None:
    """The load-bearing test. The verifier is extracted from the pack file and
    run by a separate, isolated interpreter from a directory outside the repo.
    The control assertion is the point: if `import packages` succeeded there, a
    green exit code would prove nothing about independence."""
    document = _document()
    pack_path = tmp_path / "evidence-pack.json"
    pack_path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8", newline="\n")
    script = write_verifier_script(document, tmp_path)

    control = subprocess.run(
        [sys.executable, "-I", "-S", "-c", "import packages"],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert control.returncode != 0, (
        "Milexium is importable in the subprocess, so this test cannot show the "
        "verifier ran without it"
    )
    # `-S` is load-bearing and not decoration. `-I` alone leaves `site` enabled,
    # so an editable install (`pip install -e .`, which is exactly what CI does)
    # drops a .pth file that puts the repo root back on sys.path -- and this
    # control then FAILS on CI while passing locally, where cwd alone was enough.
    # `-S` skips site processing entirely, so the isolation is real on both.
    # The verifier imports only argparse/hashlib/json/sys/dataclasses/datetime,
    # so losing site-packages costs it nothing.

    run = subprocess.run(
        [sys.executable, "-I", "-S", str(script), str(pack_path)],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert "VERIFIED" in run.stdout
    assert "NOT VERIFIED" not in run.stdout


def test_a_tampered_pack_fails_in_that_same_interpreter(tmp_path) -> None:
    """The same extraction path, on a pack whose payload was edited and whose
    checksums were both re-anchored. Exit code 1, from a process that cannot
    import a line of Milexium."""
    document = _reanchor(_tamper_payload(_document()))
    pack_path = tmp_path / "evidence-pack.json"
    pack_path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8", newline="\n")
    script = write_verifier_script(document, tmp_path)

    run = subprocess.run(
        [sys.executable, "-I", "-S", str(script), str(pack_path)],
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert run.returncode == 1, run.stdout + run.stderr
    assert "NOT VERIFIED" in run.stdout


def test_the_verifier_exits_two_on_an_unreadable_file(tmp_path) -> None:
    """A distinct exit code for "could not read" so a broken file is never
    mistaken for a failed verification -- or, worse, for a passed one."""
    script = write_verifier_script(_document(), tmp_path)
    bad = tmp_path / "not-json.json"
    bad.write_text("{ this is not json", encoding="utf-8")

    run = subprocess.run(
        [sys.executable, "-I", "-S", str(script), str(bad)], capture_output=True, text=True
    )
    assert run.returncode == 2


# --------------------------------------------------------------------------- #
# 2. Tamper cases -- each one caught, and named                                 #
# --------------------------------------------------------------------------- #


def _tamper_payload(document: dict) -> dict:
    """Rewrite the operative decision inside an embedded ledger row."""
    row = document["pack"]["raw_events"][1]
    payload = json.loads(row["payload_json"])
    payload["assignment"] = "vehicle-99"
    row["payload_json"] = sv.canonical_json(payload)
    return document


def test_tampered_payload_is_caught_by_the_bundle_checksum() -> None:
    report = _verify(_tamper_payload(_document()))

    assert not report["verified"]
    assert "pack.bundle_checksum" in report["failed"]


def test_tampered_payload_with_both_checksums_reanchored_is_still_caught() -> None:
    """The attacker wins every hash they are allowed to recompute, and loses
    anyway: the per-event hash covers the ORIGINAL payload, and the narrative
    still carries what the ledger row used to say."""
    report = _verify(_reanchor(_tamper_payload(_document())))

    assert _statuses(report)["file.checksum"] == "pass"
    assert _statuses(report)["pack.bundle_checksum"] == "pass"
    assert "chain.rehashed" in report["failed"]
    assert "narrative.matches_ledger" in report["failed"]
    assert not report["verified"]


def test_tampered_stored_hash_is_caught() -> None:
    """Editing the stored hash instead of the payload -- the other half of the
    same attack. Both checksums re-anchored; the recomputed hash disagrees."""
    document = _document()
    document["pack"]["raw_events"][0]["hash"] = "0" * 64
    report = _verify(_reanchor(document))

    assert _statuses(report)["pack.bundle_checksum"] == "pass"
    assert "chain.rehashed" in report["failed"]
    assert not report["verified"]


def test_a_spliced_chain_whose_every_hash_recomputes_is_caught_by_the_links() -> None:
    """Isolates the prev_hash linkage from the hash recomputation.

    Written because neutering the linkage check left
    `test_tampered_stored_hash_is_caught` green -- the recomputation catches
    that one too, so it does not prove the links are walked. Here the second
    row is re-pointed at a hash that is not its predecessor's and its own hash
    is RECOMPUTED correctly for the new prev_hash, so every per-event hash
    verifies in isolation. Only walking the links notices that the chain has
    been spliced.
    """
    document = _document()
    rows = document["pack"]["raw_events"]

    # Re-point row 1 away from its predecessor and recompute its own hash, so it
    # verifies in isolation and ONLY the link is wrong.
    rows[1]["prev_hash"] = "f" * 64
    rows[1]["hash"] = sv.compute_event_hash(
        rows[1]["prev_hash"],
        json.loads(rows[1]["payload_json"]),
        rows[1]["sequence"],
        rows[1]["aggregate_id"],
        rows[1]["idempotency_key"],
    )

    # Bring the narrative's copies of THIS event back into agreement, addressed
    # by event_id and field.
    #
    # A blanket string replace over the narrative JSON cannot do this correctly,
    # and the earlier attempt that did so is why this test was failing. Row 1's
    # original prev_hash IS row 0's own hash -- the same 64 characters -- so
    # replacing it everywhere also silently rewrites the narrative's copy of row
    # 0's `hash`, which the ledger still holds unchanged. The pack then fails
    # `narrative.matches_ledger` for a reason that has nothing to do with the
    # splice, and the test stops isolating the link walk.
    spliced_id = rows[1]["event_id"]
    evidence = document["pack"]["evidence"]
    for key in ("known_inputs", "proposed", "approved_or_overridden", "outcome_events"):
        section = evidence.get(key)
        if not isinstance(section, list):
            continue
        for record in section:
            if isinstance(record, dict) and record.get("event_id") == spliced_id:
                for field in ("prev_hash", "hash"):
                    if field in record:
                        record[field] = rows[1][field]
    executed = evidence.get("executed")
    if isinstance(executed, dict) and executed.get("event_id") == spliced_id:
        for field in ("prev_hash", "hash"):
            if field in executed:
                executed[field] = rows[1][field]

    report = _verify(_reanchor(document))

    statuses = _statuses(report)
    assert statuses["pack.bundle_checksum"] == "pass"
    assert statuses["narrative.matches_ledger"] == "pass", (
        "the narrative still disagrees, so this test is not isolating the link walk"
    )
    assert "chain.rehashed" in report["failed"]
    assert not report["verified"]


def test_a_rewritten_final_hash_is_caught_only_by_recomputing_it() -> None:
    """Isolates the sha256 recomputation from every other check that could also
    notice a bad hash.

    Written because neutering the recomputation left
    `test_tampered_stored_hash_is_caught` green: editing a middle row's hash
    also breaks the NEXT row's prev_hash link, so that test does not prove the
    recomputation happens. Here the LAST row is edited (no successor to break),
    the narrative's copies of that hash are rewritten to agree, and both
    checksums are re-anchored. Nothing is left but recomputing sha256 over the
    payload.
    """
    document = _document()
    rows = document["pack"]["raw_events"]
    original, forged = rows[-1]["hash"], "9" * 64
    rows[-1]["hash"] = forged
    document["pack"]["evidence"] = json.loads(
        json.dumps(document["pack"]["evidence"]).replace(original, forged)
    )
    report = _verify(_reanchor(document))

    statuses = _statuses(report)
    assert statuses["pack.bundle_checksum"] == "pass"
    assert statuses["narrative.matches_ledger"] == "pass", (
        "the narrative still disagrees, so this test is not isolating the "
        "hash recomputation it was written for"
    )
    assert "chain.rehashed" in report["failed"]
    assert not report["verified"]


def test_tampered_manifest_claim_is_caught() -> None:
    """A manifest claim is covered by NO hash at the pack layer -- the bundle
    checksum deliberately excludes the manifest. Before this packet, the
    manifest was simply believed."""
    document = _document()
    document["pack"]["manifest"]["event_count"] = 99
    report = _verify(_reanchor(document))

    assert _statuses(report)["pack.bundle_checksum"] == "pass"
    assert "manifest.event_count" in report["failed"]
    assert not report["verified"]


def test_tampered_manifest_aggregate_id_is_caught() -> None:
    document = _document()
    document["pack"]["manifest"]["aggregate_id"] = "req-someone-elses-0002"
    report = _verify(_reanchor(document))

    assert "manifest.aggregate_id_matches_evidence" in report["failed"]
    assert "manifest.aggregate_id_matches_every_row" in report["failed"]
    assert not report["verified"]


def test_tampered_timestamp_is_caught() -> None:
    """`occurred_at` is NOT an input to the per-event hash, so a re-anchored
    edit sails through chain re-verification. It is caught by the narrative
    check, which requires the reconstructed story to agree with the rows it was
    reconstructed from."""
    document = _document()
    document["pack"]["raw_events"][0]["occurred_at"] = "2026-01-01T00:00:00+00:00"
    report = _verify(_reanchor(document))

    statuses = _statuses(report)
    assert statuses["pack.bundle_checksum"] == "pass"
    assert statuses["chain.rehashed"] == "pass", (
        "if the chain check catches this, the test is not exercising the gap it "
        "was written for"
    )
    assert "narrative.matches_ledger" in report["failed"]
    assert not report["verified"]


def test_a_foreign_row_smuggled_into_the_pack_is_caught() -> None:
    document = _document()
    stranger = dict(document["pack"]["raw_events"][0])
    stranger["aggregate_id"] = "req-another-tenants-0003"
    document["pack"]["raw_events"].append(stranger)
    document["pack"]["manifest"]["event_count"] = 3
    report = _verify(_reanchor(document))

    assert "manifest.aggregate_id_matches_every_row" in report["failed"]
    assert not report["verified"]


def test_a_redaction_that_was_claimed_but_not_performed_is_caught() -> None:
    """ADR-0045's defect class, re-derived by the verifier a third party runs
    rather than by ours."""
    document = _document()
    document["pack"]["manifest"]["redacted_fields"] = ["rider_note"]
    report = _verify(_reanchor(document))

    assert "redaction.claim_holds" in report["failed"]
    assert not report["verified"]
    detail = next(c["detail"] for c in report["checks"] if c["check_id"] == "redaction.claim_holds")
    assert SENSITIVE not in detail, "a leak report that quoted the leak would be one"


def test_a_tampered_teardown_figure_is_caught_after_reanchoring() -> None:
    """The money figure is tripled and every checksum re-anchored. Re-derivation
    from the embedded segments and the manifest's declared rate catches it."""
    document = _document(_pack(teardown=_teardown_evidence()), provenance="real_public")
    figures = document["pack"]["teardown"]["figures"]
    figures["value_at_full_cost"] = figures["value_at_full_cost"] * 3
    report = _verify(_reanchor(document))

    statuses = _statuses(report)
    assert statuses["file.checksum"] == "pass"
    assert statuses["pack.bundle_checksum"] == "pass"
    assert "teardown.value_at_full_cost" in report["failed"]
    assert not report["verified"]


def test_altering_only_the_declared_rate_is_caught_which_a_re_reader_would_miss() -> None:
    """Proof of direction. The declared input changes and the money figure does
    not. A verifier that read the figure back would report success; this one
    re-derives value_at_full_cost from the rate and fails."""
    document = _document(_pack(teardown=_teardown_evidence()), provenance="real_public")
    for record in document["pack"]["teardown"]["manifest"]["inputs"]:
        if record["name"] == "cost_per_vehicle_hour":
            record["value"] = "999.0 USD"
    report = _verify(_reanchor(document))

    assert "teardown.value_at_full_cost" in report["failed"]
    assert not report["verified"]


def test_a_flattering_segment_subset_is_caught_by_the_fingerprint() -> None:
    """Dropping the worst segments and restating the totals to match keeps the
    arithmetic self-consistent; the segment fingerprint is what refuses it."""
    document = _document(_pack(teardown=_teardown_evidence()), provenance="real_public")
    teardown = document["pack"]["teardown"]
    teardown["segments"] = [s for s in teardown["segments"] if s["kind"] != "deadhead"][:2]
    teardown["manifest"]["segment_count"] = len(teardown["segments"])
    document["pack"]["manifest"]["teardown_segment_count"] = len(teardown["segments"])
    report = _verify(_reanchor(document))

    assert "teardown.segment_fingerprint" in report["failed"]
    assert not report["verified"]


def test_an_attestation_that_overclaims_fails_verification() -> None:
    """The honesty is enforced on the recipient's desk, not only in our
    constructor. A pack file edited to claim operational reality FAILS -- the
    machine-readable scope is a check, not a label."""
    document = _document()
    document["attestation"]["reflects_operational_reality"] = True
    document["attestation"]["status"] = "Validated"
    report = _verify(_reanchor(document))

    assert "attestation.reflects_operational_reality_is_false" in report["failed"]
    assert "attestation.status_not_overclaimed" in report["failed"]
    assert not report["verified"]


def test_an_attestation_that_deletes_its_limits_fails_verification() -> None:
    document = _document()
    document["attestation"]["does_not_attest"] = []
    report = _verify(_reanchor(document))

    assert "attestation.states_what_it_cannot_prove" in report["failed"]
    assert not report["verified"]


def test_a_pack_file_with_no_attestation_fails_rather_than_being_assumed_modest() -> None:
    document = _document()
    document["attestation"] = None
    report = _verify(_reanchor(document))

    assert "attestation.present" in report["failed"]
    assert not report["verified"]


def test_a_swapped_verifier_script_is_caught_by_its_digest() -> None:
    document = _document()
    document["verifier"]["source"] = "import sys\nprint('VERIFIED')\nsys.exit(0)\n"
    report = _verify(document)

    assert "file.verifier_digest" in report["failed"]
    assert "file.checksum" in report["failed"]
    assert not report["verified"]


def test_editing_any_file_level_field_breaks_the_file_checksum() -> None:
    document = _document()
    document["algorithm"][0]["rule"] = "hash it however you like"
    report = _verify(document)

    assert "file.checksum" in report["failed"]
    assert not report["verified"]


# --------------------------------------------------------------------------- #
# 3. The verifier is not a rubber stamp -- and agrees with the in-repo path      #
# --------------------------------------------------------------------------- #

_TAMPERS = {
    "payload": _tamper_payload,
    "stored_hash": lambda d: d["pack"]["raw_events"][0].__setitem__("hash", "0" * 64) or d,
    "manifest_claim": lambda d: d["pack"]["manifest"].__setitem__("event_count", 99) or d,
    "timestamp": lambda d: d["pack"]["raw_events"][0].__setitem__(
        "occurred_at", "2026-01-01T00:00:00+00:00"
    ) or d,
    "claimed_redaction": lambda d: d["pack"]["manifest"].__setitem__(
        "redacted_fields", ["rider_note"]
    ) or d,
}


@pytest.mark.parametrize("name", sorted(_TAMPERS))
def test_both_verifiers_reject_every_tamper_and_accept_the_honest_pack(name: str) -> None:
    """Two independent implementations -- `verify_evidence_pack` (Pydantic, via
    packages.verify) and the standalone script (stdlib only) -- must agree. If
    only one catches a case, the pack means something different depending on who
    checks it, and the third party is the one holding the weaker answer."""
    honest = _document()
    assert _verify(honest)["verified"]
    assert verify_evidence_pack(EvidencePack.model_validate(honest["pack"])).reverified

    tampered = _reanchor(_TAMPERS[name](_document()))
    assert not _verify(tampered)["verified"], f"standalone verifier missed {name}"
    assert not verify_evidence_pack(
        EvidencePack.model_validate(tampered["pack"])
    ).reverified, f"verify_evidence_pack missed {name}"


def test_a_skipped_check_is_never_counted_as_a_passed_one() -> None:
    """A redacted pack cannot chain-reverify by design. The verdict is NOT
    VERIFIED with the reason named -- not a quiet pass, and not a failure that
    implies the pack was altered."""
    redacted = redact_pack(_pack(), sensitive_payload_keys=("rider_note",))
    report = _verify(_document(redacted))

    assert not report["verified"]
    assert report["failed"] == [], (
        "nothing about a redacted pack is WRONG; the chain simply cannot be "
        "re-derived from masked payloads"
    )
    assert "chain.rehashed" in report["not_checkable"]


def test_the_redacted_pack_that_ships_carries_no_sensitive_value_anywhere() -> None:
    """The leak test, applied to the artifact that actually leaves: the whole
    serialized pack FILE, not a parsed subset of the pack."""
    redacted = redact_pack(_pack(), sensitive_payload_keys=("rider_note",))
    text = build_pack_file(redacted, data_provenance="synthetic").to_json()

    assert SENSITIVE not in text
    assert "[REDACTED]" in text


# --------------------------------------------------------------------------- #
# 4. Determinism -- two of these are regressions for defects found here          #
# --------------------------------------------------------------------------- #


def test_row_order_does_not_change_the_pack() -> None:
    """REGRESSION. `build_evidence_pack` embedded raw rows in whatever order the
    caller supplied them, so the same recorded history produced two different
    packs with two different bundle checksums. A recipient handed both could not
    tell "re-exported" from "altered"."""
    store, tenant_id, aggregate_id = _seeded_chain()
    events = store.history(tenant_id, aggregate_id)
    rows = list(store.raw_rows_for_tenant(tenant_id))

    forward = build_evidence_pack(events, rows)
    backward = build_evidence_pack(events, list(reversed(rows)))

    assert forward.to_json() == backward.to_json()
    assert forward.manifest.bundle_sha256 == backward.manifest.bundle_sha256


def test_redaction_key_order_does_not_change_the_pack() -> None:
    """REGRESSION. Masking a set of keys is order-independent, but the manifest
    recorded them in argument order, so the same masking produced two different
    artifacts."""
    pack = _pack()
    one = redact_pack(pack, sensitive_payload_keys=("rider_note", "assignment"))
    other = redact_pack(pack, sensitive_payload_keys=("assignment", "rider_note"))

    assert one.to_json() == other.to_json()


def test_the_pack_file_is_byte_identical_when_rebuilt() -> None:
    pack = _pack(teardown=_teardown_evidence())
    first = build_pack_file(pack, data_provenance="real_public").to_json()
    second = build_pack_file(pack, data_provenance="real_public").to_json()

    assert first == second


def test_the_pack_file_carries_no_path_from_the_machine_that_built_it() -> None:
    """An absolute path is both a determinism leak and an information leak. The
    verifier is read off disk at build time, so this is exactly the kind of
    thing that could ride in unnoticed."""
    text = build_pack_file(_pack(teardown=_teardown_evidence()), data_provenance="real_public").to_json()

    for marker in ("C:\\\\", "c:\\\\", "/home/", "/Users/", "site-packages", "Milexium\\\\packages"):
        assert marker not in text, f"the pack file leaks a build-machine path: {marker}"


def test_verification_does_not_depend_on_dict_ordering_in_the_file() -> None:
    """A recipient's JSON tooling may reorder object keys. Verification must
    survive that, because it hashes canonical JSON rather than the file's bytes."""
    document = _document(_pack(teardown=_teardown_evidence()), provenance="real_public")
    reordered = json.loads(json.dumps(document, sort_keys=True))
    shuffled = json.loads(json.dumps(reordered, sort_keys=False))

    assert _verify(shuffled)["verified"]


# --------------------------------------------------------------------------- #
# 5. The scope is structural, and the refusals are enforced at construction      #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "field",
    ["reflects_operational_reality", "consented_operator_input", "operator_data_present", "causal_claim"],
)
def test_an_attestation_cannot_be_constructed_claiming_operational_truth(field: str) -> None:
    with pytest.raises(ValidationError, match="may never be True"):
        AttestationScope(data_provenance="synthetic", note="n", **{field: True})


def test_status_stops_at_demonstrated_because_no_consented_operator_data_exists() -> None:
    with pytest.raises(ValidationError):
        AttestationScope(data_provenance="synthetic", note="n", status="Validated")


def test_there_is_no_operator_provenance_to_claim() -> None:
    with pytest.raises(ValidationError):
        AttestationScope(data_provenance="operator", note="n")


def test_the_declared_limits_cannot_be_trimmed_for_the_reader() -> None:
    kept = tuple(DOES_NOT_ATTEST[1:])
    with pytest.raises(ValidationError, match="every declared limit"):
        AttestationScope(data_provenance="synthetic", note="n", does_not_attest=kept)


def test_the_limits_name_the_two_things_a_pack_most_easily_implies() -> None:
    """Internal consistency says nothing about what was left out, and a script
    the subject of an audit supplied says nothing about the subject. Both are
    declared rather than left for the reviewer to notice."""
    assert "the_records_included_were_not_selected_by_the_issuer" in DOES_NOT_ATTEST
    assert "the_embedded_verifier_is_the_one_the_issuer_published" in DOES_NOT_ATTEST


def test_a_pack_file_cannot_overwrite_the_teardowns_record_of_its_own_provenance() -> None:
    pack = _pack(teardown=_teardown_evidence())  # real_public
    with pytest.raises(ValueError, match="disagrees with the carried teardown"):
        build_pack_file(pack, data_provenance="synthetic")

    assert build_pack_file(pack, data_provenance="mixed").attestation.data_provenance == "mixed"


def test_every_attested_claim_has_a_check_behind_it() -> None:
    """A claim key with no check is decoration -- the "restated, not re-derived"
    failure in a different costume. Each `attests` entry maps onto a check the
    verifier actually ran on a full pack."""
    document = _document(_pack(teardown=_teardown_evidence()), provenance="real_public")
    ran = {check["check_id"] for check in _verify(document)["checks"] if check["status"] == "pass"}

    for claim, check_id in {
        "bytes_unaltered_since_export": "pack.bundle_checksum",
        "hash_chain_recomputes_from_the_carried_ledger_rows": "chain.rehashed",
        "narrative_follows_from_the_carried_ledger_rows": "narrative.matches_ledger",
        "manifest_summarizes_its_own_body_truthfully": "manifest.event_count",
        "teardown_figures_follow_from_the_carried_segments_and_declared_inputs": (
            "teardown.total_deadhead_minutes"
        ),
    }.items():
        assert claim in document["attestation"]["attests"]
        assert check_id in ran, f"{claim} is attested but {check_id} never ran"


def test_a_bare_pack_is_verified_but_reported_as_carrying_no_scope() -> None:
    """Someone will hand over the inner pack without the envelope. It still
    checks, and the report says plainly that the attestation and the verifier
    were not there to check."""
    report = _verify(json.loads(_pack().to_json()))

    assert _statuses(report)["file.shape"] == "not_applicable"
    assert "attestation.present" not in _statuses(report)
    assert report["failed"] == []
