"""Fixture-level conformance: example canonical records validate against
their own exported JSON Schema, using the *independent* verifier (not
Pydantic re-validating itself). This is the "Exists" evidence for Program A's
schema contract.
"""

from __future__ import annotations

from packages.canonical import DecisionEvent, ServiceRequest, Tenant
from packages.verify import verify_against_schema

from conformance.fixtures.builders import example_service_request, example_tenant


def test_example_tenant_matches_its_own_schema() -> None:
    tenant = example_tenant()
    errors = verify_against_schema(tenant.model_dump(mode="json"), Tenant)
    assert errors == []


def test_example_service_request_matches_its_own_schema() -> None:
    tenant = example_tenant()
    request = example_service_request(tenant.tenant_id)
    errors = verify_against_schema(request.model_dump(mode="json"), ServiceRequest)
    assert errors == []


def test_schema_verifier_rejects_unknown_field() -> None:
    tenant = example_tenant()
    payload = tenant.model_dump(mode="json")
    payload["unexpected_field"] = "should not be allowed"
    errors = verify_against_schema(payload, Tenant)
    assert errors, "extra=forbid on the canonical model must surface as a schema error"


def test_schema_verifier_rejects_missing_required_field() -> None:
    tenant = example_tenant()
    payload = tenant.model_dump(mode="json")
    del payload["tenant_id"]
    errors = verify_against_schema(payload, Tenant)
    assert any("tenant_id" in e or "required" in e.lower() for e in errors)


def test_decision_event_schema_is_exportable() -> None:
    # DecisionEvent is exercised end-to-end in conformance/adversarial and
    # conformance/property-tests; here we only prove the contract itself
    # (JSON Schema export) is well-formed and self-consistent.
    from packages.verify import export_schema

    schema = export_schema(DecisionEvent)
    assert schema["title"] == "DecisionEvent"
    assert schema.get("additionalProperties") is False
