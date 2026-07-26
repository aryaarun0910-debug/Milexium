"""HTTP API conformance (Program M, v0.1 HTTP surface).

Drives the FastAPI app over HTTP with FastAPI's bundled Starlette `TestClient`
(httpx is present in this environment, so the tests exercise the real ASGI
request/response path, not the handler functions directly). Each test builds a
fresh app via `create_app()` so the in-memory store is isolated per test.

Proves the HTTP surface mirrors the SDK loop honestly: a recommendation and a
human override are recorded, the evidence packet and the portable evidence pack
are retrievable, the pack re-verifies from the HTTP response bytes alone, and a
tamper surfaces `verified=False` THROUGH the API (the app is not weakened to make
the happy path pass). Also checks the OpenAPI contract is served.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from argus.api.app import create_app, in_memory_client
from aletheia.evidence import EvidencePack, verify_evidence_pack


def _client() -> TestClient:
    return TestClient(create_app())


def _new_aggregate_id() -> str:
    return str(uuid.uuid7())


def _record_decision_and_override(c: TestClient, aggregate_id: str) -> None:
    r = c.post(
        "/decisions",
        json={
            "aggregate_id": aggregate_id,
            "actor_id": "scheduler-v1",
            "payload": {"recommended_vehicle_id": "veh-A"},
            "reason_codes": ["PICKUP_WINDOW"],
        },
    )
    assert r.status_code == 201, r.text
    r2 = c.post(
        f"/decisions/{aggregate_id}/overrides",
        json={"actor_id": "dispatcher-7", "payload": {"overridden_to_vehicle_id": "veh-C"}},
    )
    assert r2.status_code == 201, r2.text


# --- meta -------------------------------------------------------------------

def test_health_and_version() -> None:
    c = _client()
    assert c.get("/health").json() == {"status": "ok"}
    version = c.get("/version").json()
    assert set(version) == {"api_version", "sdk_version", "contract_version"}


def test_openapi_contract_is_served_and_documents_every_endpoint() -> None:
    c = _client()
    spec = c.get("/openapi.json").json()
    assert spec["openapi"].startswith("3.")
    assert set(spec["paths"]) == {
        "/health",
        "/version",
        "/decisions",
        "/decisions/{aggregate_id}/overrides",
        "/decisions/{aggregate_id}/evidence",
        "/decisions/{aggregate_id}/evidence-pack",
        "/decisions/{aggregate_id}/verify",
        # MX-M-TEARDOWN-SURFACE-004: the teardown and the intake dry-run.
        # Behaviour for both is proved in test_api_teardown.py; they are listed
        # here only to keep this an EXACT enumeration of the served surface.
        "/teardowns",
        "/operator-exports/validate",
    }
    # The evidence models are documented as reusable schema components.
    assert "EvidencePacket" in spec["components"]["schemas"]
    assert "EvidencePack" in spec["components"]["schemas"]


# --- record + read ----------------------------------------------------------

def test_record_decision_fixes_system_actor_and_returns_the_event() -> None:
    c = _client()
    aggregate_id = _new_aggregate_id()
    body = c.post(
        "/decisions",
        json={"aggregate_id": aggregate_id, "actor_id": "scheduler-v1", "payload": {"x": 1}},
    ).json()
    assert body["event_type"] == "recommendation"
    assert body["actor_type"] == "system"
    assert body["sequence"] == 1
    assert body["hash"]  # a non-empty hash-chain anchor


def test_override_fixes_human_actor_and_increments_sequence() -> None:
    c = _client()
    aggregate_id = _new_aggregate_id()
    _record_decision_and_override(c, aggregate_id)
    packet = c.get(f"/decisions/{aggregate_id}/evidence").json()
    assert packet["integrity_verified"] is True
    assert packet["executed"]["event_type"] == "override"
    assert packet["executed"]["actor_type"] == "human"


def test_evidence_pack_reverifies_from_the_http_response_bytes() -> None:
    c = _client()
    aggregate_id = _new_aggregate_id()
    _record_decision_and_override(c, aggregate_id)

    resp = c.get(f"/decisions/{aggregate_id}/evidence-pack")
    assert resp.status_code == 200
    pack = EvidencePack.model_validate(resp.json())
    assert pack.manifest.independently_verifiable is True
    # Reconstructed from the wire and re-verified without touching the server.
    assert verify_evidence_pack(pack).reverified is True


def test_verify_endpoint_reports_a_clean_chain() -> None:
    c = _client()
    aggregate_id = _new_aggregate_id()
    _record_decision_and_override(c, aggregate_id)
    body = c.get(f"/decisions/{aggregate_id}/verify").json()
    assert body["verified"] is True
    assert body["violations"] == []


# --- tamper surfaces through the API ---------------------------------------

def test_tampered_chain_surfaces_verified_false_through_the_api() -> None:
    app = create_app()
    c = TestClient(app)
    aggregate_id = _new_aggregate_id()
    _record_decision_and_override(c, aggregate_id)

    # Corrupt a stored row via the same escape hatch the adversarial tests use,
    # reached through the app's own client -- the API must not hide it.
    client = app.state.client
    recorded = client.store.history(client.tenant_id, aggregate_id)
    client.store.tamper_with_row(recorded[0].event_id, payload_json='{"tampered": true}')

    verify_body = c.get(f"/decisions/{aggregate_id}/verify").json()
    assert verify_body["verified"] is False
    assert any(v["kind"] == "hash_mismatch" for v in verify_body["violations"])

    packet = c.get(f"/decisions/{aggregate_id}/evidence").json()
    assert packet["integrity_verified"] is False


# --- error contract ---------------------------------------------------------

def test_reads_on_unknown_aggregate_are_404() -> None:
    c = _client()
    unknown = _new_aggregate_id()
    assert c.get(f"/decisions/{unknown}/evidence").status_code == 404
    assert c.get(f"/decisions/{unknown}/evidence-pack").status_code == 404
    assert c.get(f"/decisions/{unknown}/verify").status_code == 404


def test_unknown_body_field_is_rejected() -> None:
    c = _client()
    r = c.post(
        "/decisions",
        json={"aggregate_id": _new_aggregate_id(), "payload": {}, "not_a_field": 1},
    )
    assert r.status_code == 422


def test_override_requires_actor_id() -> None:
    c = _client()
    aggregate_id = _new_aggregate_id()
    r = c.post(f"/decisions/{aggregate_id}/overrides", json={"payload": {"x": 1}})
    assert r.status_code == 422


def test_unknown_reason_code_is_rejected() -> None:
    c = _client()
    r = c.post(
        "/decisions",
        json={"aggregate_id": _new_aggregate_id(), "payload": {}, "reason_codes": ["NOT_A_CODE"]},
    )
    assert r.status_code == 422


# --- injection / isolation --------------------------------------------------

def test_create_app_accepts_an_injected_client_and_apps_are_isolated() -> None:
    injected = in_memory_client(tenant_name="Injected Co")
    app = create_app(client=injected)
    assert app.state.client is injected

    # A second app has its own store: an aggregate recorded in one is unknown
    # to the other.
    c1 = TestClient(app)
    c2 = _client()
    aggregate_id = _new_aggregate_id()
    c1.post(
        "/decisions",
        json={"aggregate_id": aggregate_id, "actor_id": "s", "payload": {"x": 1}},
    )
    assert c1.get(f"/decisions/{aggregate_id}/verify").status_code == 200
    assert c2.get(f"/decisions/{aggregate_id}/verify").status_code == 404
