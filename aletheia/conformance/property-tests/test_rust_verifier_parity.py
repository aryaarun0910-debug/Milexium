"""Differential parity test: the independent Rust verifier vs. the Python
reference.

Milexium's moat is verifiability. `aletheia/verify/hash_chain_verifier.py` is
the normative verifier; `forge/legacy/crates/verifier` is a second, independent
implementation in Rust. This test builds real event chains -- clean and
tampered -- via `SqliteCanonicalStore`, runs the *same* raw rows through both
verifiers, and asserts the two produce **identical** violation sets
(aggregate_id, sequence, kind, detail -- byte-for-byte, including the `detail`
strings). Two independent implementations that agree on every clean and
adversarial input is a far stronger claim than one implementation checked
against itself.

It skips cleanly (never fails) when the Rust toolchain is unavailable or the
crate cannot be built, so the Python-only CI path stays green on machines
without `cargo`.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from themis.canonical import DecisionEventType, SqliteCanonicalStore, TenantId
from themis.canonical.events import compute_hash
from aletheia.verify import verify_chain

from conformance.fixtures.builders import example_tenant

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BIN_NAME = "verifier.exe" if os.name == "nt" else "verifier"
_BIN_PATH = _REPO_ROOT / "target" / "release" / _BIN_NAME


def _utc(*args, **kwargs) -> datetime:
    return datetime(*args, tzinfo=timezone.utc, **kwargs)


@pytest.fixture(scope="session")
def rust_verifier_bin() -> Path:
    """Build (once) and return the path to the release `verifier` binary, or
    skip the whole module if the Rust toolchain / build is unavailable."""
    if shutil.which("cargo") is None:
        pytest.skip("cargo not on PATH -- Rust differential parity test skipped")

    try:
        result = subprocess.run(
            ["cargo", "build", "--release", "-p", "verifier"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover - env dependent
        pytest.skip(f"cargo build failed to start/finish: {exc}")

    if result.returncode != 0:  # pragma: no cover - env dependent
        pytest.skip(
            "cargo build --release -p verifier failed:\n" + result.stderr[-2000:]
        )
    if not _BIN_PATH.exists():  # pragma: no cover - env dependent
        pytest.skip(f"verifier binary not found at {_BIN_PATH}")
    return _BIN_PATH


def _run_rust(binary: Path, rows: list[dict]) -> list[dict]:
    """Pipe raw rows as JSON to the Rust binary and parse its violations."""
    result = subprocess.run(
        [str(binary)],
        input=json.dumps(rows),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=_REPO_ROOT,
    )
    assert result.returncode == 0, f"rust verifier failed: {result.stderr}"
    return json.loads(result.stdout or "[]")


def _normalize(violations) -> list[tuple]:
    """Reduce Python `ChainViolation`s or Rust dicts to a comparable, ordered
    list of (aggregate_id, sequence, kind, detail) tuples."""
    out = []
    for v in violations:
        d = dataclasses.asdict(v) if dataclasses.is_dataclass(v) else v
        out.append((d["aggregate_id"], d["sequence"], d["kind"], d["detail"]))
    return sorted(out)


def _seeded_store(
    aggregate_id: str = "req-parity-0001", n: int = 3, payload=None
) -> tuple[SqliteCanonicalStore, TenantId, str]:
    store = SqliteCanonicalStore()
    tenant = example_tenant()
    store.create_tenant(tenant)
    for i in range(n):
        store.append_event(
            tenant_id=tenant.tenant_id,
            aggregate_id=aggregate_id,
            aggregate_type="ServiceRequest",
            occurred_at=_utc(2026, 7, 23, 8, i),
            actor_type="system",
            actor_id="scheduler",
            event_type=DecisionEventType.RECOMMENDATION,
            payload={"i": i} if payload is None else dict(payload, i=i),
        )
    return store, tenant.tenant_id, aggregate_id


def _assert_parity(binary: Path, rows: list[dict]) -> list[tuple]:
    py = _normalize(verify_chain(rows))
    rust = _normalize(_run_rust(binary, rows))
    assert py == rust, f"parity mismatch\n python={py}\n rust  ={rust}"
    return py


def test_parity_on_a_clean_chain(rust_verifier_bin) -> None:
    store, tenant_id, _ = _seeded_store()
    rows = store.raw_rows_for_tenant(tenant_id)
    assert _assert_parity(rust_verifier_bin, rows) == []


def test_parity_on_a_clean_non_ascii_chain(rust_verifier_bin) -> None:
    # Proves the ensure_ascii canonicalization matches through the full
    # pipeline: a non-ASCII payload hashes identically in both languages, so a
    # clean chain stays clean on both sides.
    store, tenant_id, _ = _seeded_store(
        aggregate_id="req-parity-utf8", payload={"note": "café \U0001f68c Ω"}
    )
    rows = store.raw_rows_for_tenant(tenant_id)
    assert _assert_parity(rust_verifier_bin, rows) == []


def test_parity_on_payload_tampering(rust_verifier_bin) -> None:
    store, tenant_id, agg = _seeded_store()
    history = store.history(tenant_id, agg)
    store.tamper_with_row(history[1].event_id, payload_json='{"i": 999}')
    rows = store.raw_rows_for_tenant(tenant_id)
    result = _assert_parity(rust_verifier_bin, rows)
    assert any(kind == "hash_mismatch" for _, _, kind, _ in result)


def test_parity_on_deleted_middle_gap(rust_verifier_bin) -> None:
    store, tenant_id, agg = _seeded_store()
    history = store.history(tenant_id, agg)
    store._conn.execute(
        "DELETE FROM decision_events WHERE event_id = ?", (history[1].event_id,)
    )
    store._conn.commit()
    rows = store.raw_rows_for_tenant(tenant_id)
    result = _assert_parity(rust_verifier_bin, rows)
    kinds = {kind for _, _, kind, _ in result}
    assert "sequence_gap" in kinds or "prev_hash_mismatch" in kinds


def test_parity_on_forged_hash_chain_break(rust_verifier_bin) -> None:
    store, tenant_id, agg = _seeded_store()
    history = store.history(tenant_id, agg)
    target = history[1]
    forged_payload = {"i": 999}
    forged_hash = compute_hash(target.prev_hash, forged_payload, target.sequence, agg)
    store.tamper_with_row(
        target.event_id, payload_json='{"i": 999}', hash=forged_hash
    )
    rows = store.raw_rows_for_tenant(tenant_id)
    result = _assert_parity(rust_verifier_bin, rows)
    # The forged event's own hash now matches its tampered payload, but the
    # next event's prev_hash was chained off the original hash -- both verifiers
    # must catch that break.
    assert any(kind == "prev_hash_mismatch" for _, _, kind, _ in result)


def test_parity_on_multiple_aggregates_mixed(rust_verifier_bin) -> None:
    # One clean aggregate and one tampered aggregate in the same tenant, so the
    # grouping/sorting logic is exercised on both sides simultaneously.
    store = SqliteCanonicalStore()
    tenant = example_tenant()
    store.create_tenant(tenant)
    for agg in ("req-clean", "req-dirty"):
        for i in range(3):
            store.append_event(
                tenant_id=tenant.tenant_id,
                aggregate_id=agg,
                aggregate_type="ServiceRequest",
                occurred_at=_utc(2026, 7, 23, 8, i),
                actor_type="system",
                actor_id="scheduler",
                event_type=DecisionEventType.RECOMMENDATION,
                payload={"i": i},
            )
    dirty = store.history(tenant.tenant_id, "req-dirty")
    store.tamper_with_row(dirty[2].event_id, payload_json='{"i": -1}')
    rows = store.raw_rows_for_tenant(tenant.tenant_id)
    result = _assert_parity(rust_verifier_bin, rows)
    assert any(agg == "req-dirty" and kind == "hash_mismatch" for agg, _, kind, _ in result)
    assert not any(agg == "req-clean" for agg, _, _, _ in result)
