"""Milexium HTTP API (Program M, v0.1 HTTP surface).

A thin FastAPI application that exposes the same decision loop as the
`MilexiumClient` Python SDK over HTTP, so software that is *not* written in
Python can integrate the runtime -- the "others integrate this" unlock that the
SDK began and this layer extends past the Python boundary.

It is pure composition over `packages.sdk.MilexiumClient`; it adds no domain
logic, only an HTTP contract and Pydantic request/response bodies. The endpoint
set is deliberately narrow and mirrors the SDK surface one-to-one:

    GET  /health                                   liveness
    GET  /version                                  API / SDK / contract versions
    POST /decisions                                record a RECOMMENDATION (system act)
    POST /decisions/{aggregate_id}/overrides       record an OVERRIDE (human act)
    GET  /decisions/{aggregate_id}/evidence        the reconstructed EvidencePacket
    GET  /decisions/{aggregate_id}/evidence-pack   the portable, self-verifying EvidencePack
    GET  /decisions/{aggregate_id}/verify          independent hash-chain check

The OpenAPI schema FastAPI serves at **/openapi.json** (human-browsable at
**/docs**) is the machine-readable API contract -- a non-Python client generates
its own bindings from it.

Deliberately NOT in this v0.1 HTTP slice:

- **Ingestion and forecast endpoints.** Ingestion drives a Python
  `SourceAdapter` object and forecasting needs a model registry + on-disk model
  artifacts; both are Python objects/files that do not map honestly onto a
  JSON-over-HTTP body yet. They stay on the SDK (`client.ingest`,
  `client.forecast`) and are Specified for the HTTP surface.
- **Auth, the multi-tenant API gateway, and rate limiting.** OUT of scope
  (Specified). This app is backed by ONE `MilexiumClient` bound to ONE
  in-memory tenant; there is no per-request tenant resolution, no credential
  check, and no quota. A real deployment injects a Postgres-backed store
  (`packages.canonical` PostgresCanonicalStore) and puts tenant auth in front --
  none of which this slice fakes.

Status: Demonstrated (drives the real in-memory loop end to end over HTTP);
not Validated, not Production.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict

from packages.canonical import (
    DecisionEvent,
    ReasonCode,
    SqliteCanonicalStore,
    Tenant,
    TenantId,
    new_id,
)
from packages.evidence import EvidencePack, EvidencePacket
from packages.sdk import CONTRACT_VERSION, MilexiumClient
from packages.sdk import __version__ as SDK_VERSION

API_VERSION = "0.1.0"


def in_memory_client(tenant_name: str = "Milexium API in-memory demo tenant") -> MilexiumClient:
    """The demo store-backing seam: an in-memory `MilexiumClient` whose SQLite
    connection tolerates cross-thread access (`check_same_thread=False`).

    The ASGI server touches the store from a different thread than the one
    `create_app` ran on, so the default (thread-affine) `MilexiumClient.in_memory`
    connection would raise. Access stays serial -- the endpoint handlers are
    `async` and hold no `await` across a store call, so they run one at a time on
    the event loop -- so relaxing the check does not permit unsafe concurrent use.
    A real deployment injects a Postgres-backed store instead of this demo one.
    """
    store = SqliteCanonicalStore(connection=sqlite3.connect(":memory:", check_same_thread=False))
    tenant = Tenant(
        tenant_id=new_id(TenantId), name=tenant_name, created_at=datetime.now(timezone.utc)
    )
    store.create_tenant(tenant)
    return MilexiumClient(store, tenant.tenant_id)


# --- request bodies ---------------------------------------------------------

class RecordDecisionRequest(BaseModel):
    """Body for `POST /decisions`. `actor_type` is not a field: the endpoint
    fixes it to "system" (a recommendation is a system act), exactly as
    `MilexiumClient.record_decision` does."""

    model_config = ConfigDict(extra="forbid")

    aggregate_id: str
    payload: dict
    actor_id: str = "system"
    aggregate_type: str = "ServiceRequest"
    reason_codes: tuple[ReasonCode, ...] = ()
    occurred_at: datetime | None = None
    idempotency_key: str | None = None


class RecordOverrideRequest(BaseModel):
    """Body for `POST /decisions/{aggregate_id}/overrides`. `aggregate_id` comes
    from the path; `actor_id` (the human overriding) is required, not
    defaulted -- mirroring `MilexiumClient.record_override`."""

    model_config = ConfigDict(extra="forbid")

    payload: dict
    actor_id: str
    aggregate_type: str = "ServiceRequest"
    reason_codes: tuple[ReasonCode, ...] = ()
    occurred_at: datetime | None = None
    idempotency_key: str | None = None


# --- response bodies --------------------------------------------------------

class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str


class VersionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_version: str
    sdk_version: str
    contract_version: str


class RecordedEvent(BaseModel):
    """The wire projection of a recorded `DecisionEvent`. An API-owned model, so
    the HTTP contract is decoupled from the internal canonical entity; typed
    UUIDv7 ids and enums are projected to plain strings."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    tenant_id: str
    aggregate_id: str
    aggregate_type: str
    sequence: int
    occurred_at: datetime
    actor_type: str
    actor_id: str
    event_type: str
    payload: dict
    reason_codes: tuple[str, ...]
    idempotency_key: str | None
    prev_hash: str | None
    hash: str

    @classmethod
    def from_event(cls, event: DecisionEvent) -> "RecordedEvent":
        return cls(
            event_id=str(event.event_id),
            tenant_id=str(event.tenant_id),
            aggregate_id=event.aggregate_id,
            aggregate_type=event.aggregate_type,
            sequence=event.sequence,
            occurred_at=event.occurred_at,
            actor_type=event.actor_type,
            actor_id=event.actor_id,
            event_type=event.event_type.value,
            payload=event.payload,
            reason_codes=tuple(rc.value for rc in event.reason_codes),
            idempotency_key=event.idempotency_key,
            prev_hash=event.prev_hash,
            hash=event.hash,
        )


class VerifyViolation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aggregate_id: str
    sequence: int
    kind: str
    detail: str


class VerifyResponse(BaseModel):
    """Result of the independent hash-chain check. `verified` is True iff the
    verifier found zero violations -- the same meaning as the SDK's empty tuple,
    not a stronger claim."""

    model_config = ConfigDict(extra="forbid")
    aggregate_id: str
    verified: bool
    violations: tuple[VerifyViolation, ...]


def create_app(client: MilexiumClient | None = None) -> FastAPI:
    """Build the app over a `MilexiumClient`. The client is injectable so tests
    (and a real deployment swapping the in-memory store for a Postgres-backed
    one) can supply their own; the default is a single in-memory tenant."""
    client = client or in_memory_client()

    app = FastAPI(title="Milexium API", version=API_VERSION, description=__doc__)
    app.state.client = client

    def get_client() -> MilexiumClient:
        return app.state.client

    @app.get("/health", response_model=HealthResponse, tags=["meta"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/version", response_model=VersionResponse, tags=["meta"])
    async def version() -> VersionResponse:
        return VersionResponse(
            api_version=API_VERSION,
            sdk_version=SDK_VERSION,
            contract_version=CONTRACT_VERSION,
        )

    @app.post("/decisions", response_model=RecordedEvent, status_code=201, tags=["decisions"])
    async def record_decision(
        body: RecordDecisionRequest, c: MilexiumClient = Depends(get_client)
    ) -> RecordedEvent:
        try:
            event = c.record_decision(
                aggregate_id=body.aggregate_id,
                payload=body.payload,
                actor_id=body.actor_id,
                aggregate_type=body.aggregate_type,
                occurred_at=body.occurred_at,
                reason_codes=body.reason_codes,
                idempotency_key=body.idempotency_key,
            )
        except ValueError as exc:  # includes Pydantic ValidationError (e.g. a naive occurred_at)
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return RecordedEvent.from_event(event)

    @app.post(
        "/decisions/{aggregate_id}/overrides",
        response_model=RecordedEvent,
        status_code=201,
        tags=["decisions"],
    )
    async def record_override(
        aggregate_id: str, body: RecordOverrideRequest, c: MilexiumClient = Depends(get_client)
    ) -> RecordedEvent:
        try:
            event = c.record_override(
                aggregate_id=aggregate_id,
                payload=body.payload,
                actor_id=body.actor_id,
                aggregate_type=body.aggregate_type,
                occurred_at=body.occurred_at,
                reason_codes=body.reason_codes,
                idempotency_key=body.idempotency_key,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return RecordedEvent.from_event(event)

    @app.get(
        "/decisions/{aggregate_id}/evidence",
        response_model=EvidencePacket,
        tags=["evidence"],
    )
    async def evidence(aggregate_id: str, c: MilexiumClient = Depends(get_client)) -> EvidencePacket:
        try:
            return c.evidence_for(aggregate_id)
        except ValueError as exc:  # builder raises when the aggregate has no history
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get(
        "/decisions/{aggregate_id}/evidence-pack",
        response_model=EvidencePack,
        tags=["evidence"],
    )
    async def evidence_pack(aggregate_id: str, c: MilexiumClient = Depends(get_client)) -> EvidencePack:
        try:
            return c.export_pack(aggregate_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get(
        "/decisions/{aggregate_id}/verify",
        response_model=VerifyResponse,
        tags=["evidence"],
    )
    async def verify(aggregate_id: str, c: MilexiumClient = Depends(get_client)) -> VerifyResponse:
        # 404 an unknown aggregate rather than reporting verified=True over no
        # rows, so all three read-by-aggregate endpoints behave consistently.
        if not c.store.history(c.tenant_id, aggregate_id):
            raise HTTPException(
                status_code=404, detail=f"no decision history for aggregate {aggregate_id!r}"
            )
        violations = c.verify(aggregate_id)
        return VerifyResponse(
            aggregate_id=aggregate_id,
            verified=len(violations) == 0,
            violations=tuple(
                VerifyViolation(
                    aggregate_id=v.aggregate_id, sequence=v.sequence, kind=v.kind, detail=v.detail
                )
                for v in violations
            ),
        )

    return app


app = create_app()
