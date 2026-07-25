"""Milexium HTTP API (Program M, v0.1 HTTP surface).

A thin FastAPI application that exposes the same decision loop as the
`MilexiumClient` Python SDK over HTTP, so software that is *not* written in
Python can integrate the runtime -- the "others integrate this" unlock that the
SDK began and this layer extends past the Python boundary.

It is pure composition over `packages.sdk.MilexiumClient`; it adds no domain
logic, only an HTTP contract and Pydantic request/response bodies. Every
endpoint below is a call to one SDK method -- mostly one-to-one, except
`/operator-exports/validate`, which loops `client.ingest` a row at a time so it
can attribute each verdict to a row index. The endpoint set is deliberately
narrow:

    GET  /health                                   liveness
    GET  /version                                  API / SDK / contract versions
    POST /decisions                                record a RECOMMENDATION (system act)
    POST /decisions/{aggregate_id}/overrides       record an OVERRIDE (human act)
    GET  /decisions/{aggregate_id}/evidence        the reconstructed EvidencePacket
    GET  /decisions/{aggregate_id}/evidence-pack   the portable, self-verifying EvidencePack
    GET  /decisions/{aggregate_id}/verify          independent hash-chain check
    POST /teardowns                                deadhead teardown over trip segments (ADR-0039)
    POST /operator-exports/validate                dry-run intake check on an export sample (ADR-0038)

The OpenAPI schema FastAPI serves at **/openapi.json** (human-browsable at
**/docs**) is the machine-readable API contract -- a non-Python client generates
its own bindings from it.

WHY THESE TWO GOT AN HTTP ENDPOINT AND INGESTION STILL DOES NOT
ADR-0021 excluded ingestion and forecast from HTTP for one reason: their inputs
are *Python objects and on-disk files* (a `SourceAdapter` instance; a model
registry plus xgboost artifacts), and pretending otherwise would mean inventing
a JSON stand-in for something that is not JSON. That reasoning is respected
here, not worked around -- it simply does not apply to these two:

- A `VehicleSegment` is four scalars (start, end, revenue-or-deadhead, run
  reference). It is already a JSON object; a JSON POST body is its honest
  shape, not a wrapper around one. So `POST /teardowns` takes segments inline.
- The operator-export *validation* path is configured entirely by a JSON
  `column_map` over a named, concrete adapter -- no Python object crosses the
  boundary -- and it does not ingest anything, so ADR-0021's objection (an
  adapter is a Python object) has nothing to bite on.

Deliberately NOT done, with reasons rather than silence:

- **No multipart/CSV upload on either endpoint.** Tempting for a big export,
  but it would put CSV parsing, type coercion and header handling in the API,
  which is Connect adapter work with an existing owner; it would also give the
  validation endpoint a file on disk (Starlette spools uploads), which is
  exactly what an endpoint promising to persist nothing should not have. Both
  endpoints therefore take bounded JSON and refuse oversize bodies with 413,
  pointing bulk callers at the SDK (`client.teardown_deadhead`), which has no
  size ceiling at all.
- **No "tear down my raw export" endpoint.** Turning export rows into segments
  requires deciding which rows are revenue and which are deadhead, and
  `packages.replay.teardown` deliberately refuses to infer that from geometry
  or timing -- the caller's adapter decides. An HTTP endpoint that guessed it
  would be inventing the one judgment the module refuses to make.
- **Generic ingestion and forecast endpoints.** Unchanged from ADR-0021: they
  stay on the SDK (`client.ingest`, `client.forecast`) and are Specified for
  HTTP.
- **Auth, the multi-tenant API gateway, and rate limiting.** OUT of scope
  (Specified). This app is backed by ONE `MilexiumClient` bound to ONE
  in-memory tenant; there is no per-request tenant resolution, no credential
  check, and no quota. A real deployment injects a Postgres-backed store
  (`packages.canonical` PostgresCanonicalStore) and puts tenant auth in front --
  none of which this slice fakes.

The two new endpoints are also the only place this package names a *concrete*
adapter (`OperatorExportAdapter`). That asymmetry is deliberate: the SDK core
stays generic over `SourceAdapter` (ADR-0015), while an HTTP surface has no
choice but to name the thing it exposes, because a caller cannot hand a URL a
Python class.

Status: Demonstrated (drives the real in-memory loop end to end over HTTP);
not Validated, not Production.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator

from packages.canonical import (
    DecisionEvent,
    ReasonCode,
    SqliteCanonicalStore,
    Tenant,
    TenantId,
    new_id,
)
from packages.connect.operator_export import (
    CANONICAL_COLUMNS,
    PII_CATEGORIES,
    REDACTION_MARKER,
    OperatorExportAdapter,
)
from packages.evidence import EvidencePack, EvidencePacket
from packages.replay.teardown import (
    DEFAULT_REDUCTION_FRACTION,
    CostBasis,
    DataProvenance,
    DeadheadTeardown,
    TeardownError,
    VehicleSegment,
)
from packages.sdk import CONTRACT_VERSION, MilexiumClient
from packages.sdk import __version__ as SDK_VERSION

API_VERSION = "0.1.0"

MAX_TEARDOWN_SEGMENTS = 20_000
"""Ceiling on segments in ONE `POST /teardowns` body. A teardown is O(n) and
holds everything in memory; 20k segments is roughly a mid-size operator's month
and already a multi-megabyte body. Above it the request is refused with 413 and
the caller is pointed at the SDK, which has no ceiling -- better than silently
truncating the input, which would understate every total in the answer."""

MAX_VALIDATION_ROWS = 1_000
"""Ceiling on rows in ONE `POST /operator-exports/validate` body. The endpoint
exists to check a SAMPLE of an extract before real data is sent, so a small
bound is the honest scope rather than a limitation; 413 above it."""


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


class TeardownRequest(BaseModel):
    """Body for `POST /teardowns` -- the arguments of
    `MilexiumClient.teardown_deadhead`, one-to-one.

    The field list is the whole refusal surface, so read what is ABSENT:

    - There is no `is_guaranteed_saving` and no `causal_proof`. `extra="forbid"`
      means sending either is a 422, not a silently ignored field -- an API that
      accepted them would be advertising a claim the analysis refuses to make.
    - `data_provenance` is the `DataProvenance` Literal, which has no "operator"
      value, so an HTTP caller cannot label anything as operator data either.
    - `cost_basis.avoidable_share_low/high` still have no default. Omit them and
      you get the accounting value of the empty time and NO envelope, with
      `envelope_basis` stating that the recoverable fraction is unknown.

    `segments` are `VehicleSegment` models straight from `packages.replay`, not
    an API-local copy, so the domain's own construction rules (UTC-aware
    timestamps, end-not-before-start, the 48h parsing-artefact ceiling, and
    `extra="forbid"` blocking a rider field from being attached to a segment)
    are enforced on the wire rather than restated and allowed to drift.
    """

    model_config = ConfigDict(extra="forbid")

    segments: tuple[VehicleSegment, ...]
    dataset_label: str
    data_provenance: DataProvenance
    run_ref_source: str
    cost_basis: CostBasis | None = None
    reduction_fraction: float = DEFAULT_REDUCTION_FRACTION
    top_n_runs: int = 10
    unmeasured_segments: int = 0
    unmeasured_reason: str | None = None


class OperatorExportValidationRequest(BaseModel):
    """Body for `POST /operator-exports/validate`: a SAMPLE of an operator's
    export, plus the `column_map` they intend to send it with.

    `rows` are raw export rows exactly as the agency's extract produces them --
    the same `list[dict]` the adapter takes. They are checked and discarded;
    see the endpoint docstring for what "discarded" means precisely.
    """

    model_config = ConfigDict(extra="forbid")

    rows: list[dict]
    column_map: dict[str, str] | None = None


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


NOTHING_PERSISTED_NOTE = (
    "Nothing from this request was stored. The rows were parsed in memory against "
    "an ephemeral tenant id that belongs to no store, the resulting canonical "
    "records were discarded without ever being written, and no value from any row "
    "is echoed back below -- only column NAMES, counts and reasons."
)


class SemanticLossNote(BaseModel):
    """One semantic-loss note the adapter attached to an accepted row, projected
    for the wire WITHOUT `SemanticLossRecord.source_value`.

    The adapter already nulls `source_value` everywhere personal data could hide
    (unmapped extensions, the rider reference). Dropping the field entirely at
    the API boundary means that guarantee does not depend on the adapter's field
    policy staying exactly as it is: a validation response cannot carry a source
    value because the model has nowhere to put one. The `reason` text is what
    the operator needs anyway -- it says what was lost and why."""

    model_config = ConfigDict(extra="forbid")

    source_field: str
    disposition: str
    reason: str


class RowValidation(BaseModel):
    """What WOULD happen to one sample row on a real import.

    `reason` is the adapter's own quarantine text, which names offending columns
    by NAME and never quotes a rejected identifier's value. `pii_columns` is
    derived from the adapter's redaction of its own quarantine record (the
    columns it replaced with `REDACTION_MARKER`), so it reports which columns to
    strip without this layer re-running -- or weakening -- the PII check."""

    model_config = ConfigDict(extra="forbid")

    row_index: int
    accepted: bool
    pii_rejection: bool
    pii_columns: tuple[str, ...]
    reason: str | None
    failed_field: str | None
    semantic_loss: tuple[SemanticLossNote, ...]


class OperatorExportValidationResponse(BaseModel):
    """The dry-run verdict on a sample export.

    `persisted` is fixed False and RAISES if set True, the same structural
    refusal `DeadheadTeardown.causal_proof` uses: the non-persistence promise is
    encoded in the response model, not only in prose."""

    model_config = ConfigDict(extra="forbid")

    rows_checked: int
    accepted: int
    quarantined: int
    pii_rejected: int
    persisted: bool = False
    persistence_note: str = NOTHING_PERSISTED_NOTE
    canonical_columns: tuple[str, ...] = CANONICAL_COLUMNS
    pii_categories: tuple[str, ...] = PII_CATEGORIES
    results: tuple[RowValidation, ...]

    @field_validator("persisted")
    @classmethod
    def _nothing_is_ever_persisted(cls, value: bool) -> bool:
        if value:
            raise ValueError(
                "the export validation endpoint stores nothing; a response claiming "
                "otherwise would misdescribe what the endpoint did"
            )
        return value


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

    @app.post("/teardowns", response_model=DeadheadTeardown, tags=["teardown"])
    async def teardown(
        body: TeardownRequest, c: MilexiumClient = Depends(get_client)
    ) -> DeadheadTeardown:
        """Localise non-revenue ("empty") vehicle time to hours, days and runs.

        The response is the `DeadheadTeardown` itself, NOT an API-local
        projection of it. That is the point: the hedging is carried in fields
        (`interpretation`, `is_modelled`, `causal_proof`, `manifest.note`,
        `manifest.replay_discipline_note`, `cost.hedge`, `cost.envelope_basis`),
        and any re-projection here would be a second place those fields could be
        dropped from. A caller reading this over HTTP gets the same refusals a
        caller holding the Python object does.

        What it returns is a MODELLED localisation of where empty time sat --
        not causal proof that anything caused it, and not a promised saving. Any
        money figure is the accounting value of that time at the operator's own
        rate, hedged by the fixed-versus-variable split they supplied (and with
        no envelope at all if they did not supply one).

        Stateless: no segment, and nothing derived from one, is written to the
        canonical store. Verb POST because the body carries the input, not
        because anything is created server-side.
        """
        if len(body.segments) > MAX_TEARDOWN_SEGMENTS:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"{len(body.segments)} segments exceeds this endpoint's ceiling of "
                    f"{MAX_TEARDOWN_SEGMENTS}. The teardown is not truncated to fit, because a "
                    "truncated teardown understates every total it reports; drive "
                    "MilexiumClient.teardown_deadhead directly for a full export, or split the "
                    "request by observation window."
                ),
            )
        try:
            return c.teardown_deadhead(
                body.segments,
                dataset_label=body.dataset_label,
                data_provenance=body.data_provenance,
                run_ref_source=body.run_ref_source,
                cost_basis=body.cost_basis,
                reduction_fraction=body.reduction_fraction,
                top_n_runs=body.top_n_runs,
                unmeasured_segments=body.unmeasured_segments,
                unmeasured_reason=body.unmeasured_reason,
            )
        except (TeardownError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post(
        "/operator-exports/validate",
        response_model=OperatorExportValidationResponse,
        tags=["intake"],
    )
    async def validate_operator_export(
        body: OperatorExportValidationRequest, c: MilexiumClient = Depends(get_client)
    ) -> OperatorExportValidationResponse:
        """Dry-run an operator export sample: which rows would import, which
        would quarantine, and why -- WITHOUT storing anything.

        NOTHING IS PERSISTED. Concretely, and in the order it matters:

        1. The adapter is constructed against `new_id(TenantId)` -- an ephemeral
           tenant that exists for the duration of this call and is registered
           with no store, so the canonical records it produces have nowhere they
           could be written even by mistake.
        2. `client.ingest` parses in memory and returns a summary; it issues no
           write (the store is only touched by `record_decision`/
           `record_override`). The parsed records are dropped when this function
           returns.
        3. No row VALUE is echoed back. The response carries counts, column
           NAMES, the adapter's own reason text and its semantic-loss reasons.

        (3) is what makes this safe to point at a real extract. The adapter
        redacts direct identifiers out of its own quarantine record; this
        endpoint additionally never returns that record, so a rejected rider
        name cannot reach the response even in redacted form -- the operator is
        told WHICH COLUMN to strip, which is the actionable part, and is never
        shown the value back.

        Rows are parsed one at a time through the SDK so each verdict can be
        attributed to its row index; the batch runner flattens that.
        """
        if len(body.rows) > MAX_VALIDATION_ROWS:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"{len(body.rows)} rows exceeds this endpoint's ceiling of "
                    f"{MAX_VALIDATION_ROWS}. This is a pre-flight check on a SAMPLE of an "
                    "extract, not an import path; send a representative slice."
                ),
            )
        try:
            adapter = OperatorExportAdapter(
                new_id(TenantId),
                recorded_at=datetime.now(timezone.utc),
                column_map=body.column_map,
            )
        except ValueError as exc:  # an unusable column_map -- reject, do not guess
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        results: list[RowValidation] = []
        for index, row in enumerate(body.rows):
            summary = c.ingest(adapter, [row])
            quarantine = summary.quarantined_rows[0] if summary.quarantined_rows else None
            pii_columns = (
                ()
                if quarantine is None
                else tuple(
                    sorted(
                        str(column)
                        for column, value in quarantine.raw_row.items()
                        if value == REDACTION_MARKER
                    )
                )
            )
            results.append(
                RowValidation(
                    row_index=index,
                    accepted=quarantine is None,
                    pii_rejection=bool(pii_columns),
                    pii_columns=pii_columns,
                    reason=None if quarantine is None else quarantine.reason,
                    failed_field=None if quarantine is None else quarantine.failed_field,
                    semantic_loss=tuple(
                        SemanticLossNote(
                            source_field=note.source_field,
                            disposition=note.disposition,
                            reason=note.reason,
                        )
                        for note in summary.semantic_loss
                    ),
                )
            )

        return OperatorExportValidationResponse(
            rows_checked=len(results),
            accepted=sum(1 for r in results if r.accepted),
            quarantined=sum(1 for r in results if not r.accepted),
            pii_rejected=sum(1 for r in results if r.pii_rejection),
            results=tuple(results),
        )

    return app


app = create_app()
