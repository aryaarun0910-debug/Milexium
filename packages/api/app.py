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
  size ceiling -- and which is synchronous, so the 413 now says what that costs
  (`client.estimate_teardown_seconds`) instead of presenting "no ceiling" as
  free.
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
- **An async job/poll path for `POST /teardowns`.** Considered and rejected for
  this surface -- see `_TeardownRoute` below for the measurement and the three
  reasons. It remains the right answer for a real deployment.

TEARDOWN LATENCY ON THIS SURFACE (ADR-0056)
ADR-0056 measured `packages.replay.teardown` and recorded a latency defect it
found on the way past: ~46 s at a mid-size operator's year. Measuring THIS
surface (Python 3.14, i7-10510U, in-process TestClient, synthetic segments)
located where that actually bites, and it is not where the prose suggested:

The SAME measurement, same code, run twice -- once with the machine busy and
once with it quiet. Both are shown because the difference between them is the
single most important caveat on every number here:

| request                          | before (busy / quiet) | after (busy / quiet) |
|----------------------------------|----------------------:|---------------------:|
| 20,000 segments (the ceiling)    |     1.530 s / 0.607 s |    1.984 s / 0.542 s |
| the SAME body again              |     1.530 s / 0.607 s |    0.046 s / 0.011 s |
| 25,000 segments -> 413 (count)   |     0.595 s / 0.221 s |    0.620 s / 0.241 s |
| 600,000 segments -> 413 (size)   |    31.269 s / 7.378 s |    0.076 s / 0.025 s |

(each cell the minimum of 5 alternating rounds, with BOTH versions of this app
live in one process so machine state hits them equally. ADR-0056 recorded
wall-clock swinging ~2.8x with thermal state; between these two runs it swung
4.2x. A before/after taken in separate processes minutes apart would have
measured the laptop, not the change.)

So the ABSOLUTE seconds are not a property of the code. The RATIOS are, and they
are what this claims:

- **Refusing a 600,000-segment body: 295-411x faster.** The defect.
- **Repeating an identical 20,000-segment body: 33-55x faster.** The cache.
- **A FIRST 20,000-segment teardown: unchanged.** After was 1.30x slower on the
  busy run and 0.89x -- i.e. faster -- on the quiet one. Bracketing 1.0 in both
  directions is what settles it. The cache does add one SHA-256 over the body to
  every miss (26.9 ms at 20,000 segments, ~2-4% of the call); that is arithmetic,
  not something this instrument can see.

The accepted path was never 46 s: `MAX_TEARDOWN_SEGMENTS` already bounds it, and
it STILL COSTS THAT -- the first row is the honest headline, not the second. The
46 s lives on the SDK, which has no ceiling -- and the old 413 text sent bulk
callers straight at it.

What WAS broken here is the refusal: the segment-count guard is checked inside
the handler, i.e. after FastAPI has validated every segment in the body, so a
600k-segment request -- the top of ADR-0056's own operator-year band, exactly
the request that ADR invites -- burnt 7-31 s of server CPU to compute nothing
and answer 413. Two fixes, both at the surface, neither touching the analysis:

1. `MAX_TEARDOWN_BODY_BYTES` refuses an oversize body from `content-length`,
   BEFORE the body is read or parsed.
2. A bounded, content-addressed result cache keyed on the raw request bytes, so
   an identical repeat request is answered without re-parsing or re-analysing.

Neither makes a first-time teardown faster, and neither touches the SDK's
unbounded synchronous path -- `MilexiumClient.estimate_teardown_seconds` only
makes that wait a decision instead of a surprise. An async job+poll path is
still the right answer for a real deployment, and `_TeardownRoute` records the
three things it needs first.

The two new endpoints are also the only place this package names a *concrete*
adapter (`OperatorExportAdapter`). That asymmetry is deliberate: the SDK core
stays generic over `SourceAdapter` (ADR-0015), while an HTTP surface has no
choice but to name the thing it exposes, because a caller cannot hand a URL a
Python class.

Status: Demonstrated (drives the real in-memory loop end to end over HTTP);
not Validated, not Production.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Awaitable, Callable

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.routing import APIRoute
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

MAX_TEARDOWN_BODY_BYTES = 8 * 1024 * 1024
"""Ceiling on the RAW BODY of `POST /teardowns`, checked before the body is read
or parsed -- the cheap outer guard in front of the exact `MAX_TEARDOWN_SEGMENTS`
count guard.

Why two guards and not one: the count is only knowable after every segment has
been validated, so the count guard alone made a refusal cost as much as an
answer. A 600,000-segment body (71 MB) took 7.4-31.3 s to reject depending only
on how busy the laptop was -- ADR-0056's own operator-year band, spent computing
nothing. The byte guard reads `content-length` and answers the same 413 in
0.025-0.076 s: 295-411x faster on the same two runs.

8 MiB is deliberately LOOSE, not tuned: the 20,000-segment measurement ran
119 bytes/segment (2.37 MB), so this admits ~400 bytes/segment at the count
ceiling and no realistic 20,000-segment body is refused by it. The tradeoff is
stated rather than hidden -- a body with `run_ref` strings averaging over ~400
bytes IS refused on size even though its segment count is legal, and the 413
says so.

What it does NOT fix, measured rather than glossed: a body BETWEEN
`MAX_TEARDOWN_SEGMENTS` and 8 MiB still pays full validation before the count
guard sees it -- 0.24-0.62 s at 25,000 segments, 3.88 s at 70,788 (the largest
body that fits under the ceiling). The guard bounds wasted refusal work at a few
seconds; it does not eliminate it. Closing that band would mean lowering the
byte ceiling until it started refusing legal 20,000-segment bodies, which is a
worse trade."""

MAX_VALIDATION_ROWS = 1_000
"""Ceiling on rows in ONE `POST /operator-exports/validate` body. The endpoint
exists to check a SAMPLE of an extract before real data is sent, so a small
bound is the honest scope rather than a limitation; 413 above it.

NOT protected by a pre-parse byte guard -- see `_TeardownRoute`. That endpoint
takes `list[dict]`, which is far cheaper per row than 20,000 Pydantic
`VehicleSegment` models, so it is a smaller instance of the same shape rather
than the one this packet measured. Named, not fixed."""

DEFAULT_TEARDOWN_CACHE_ENTRIES = 16
"""How many teardown results `create_app` keeps. Small on purpose: a result is
tens of KB (43 KB at 20,000 segments), so 16 entries is under a megabyte, and an
unbounded cache on an endpoint with no auth and no quota is a memory-growth
primitive for anyone who can reach it. `create_app(teardown_cache_entries=0)`
turns it off entirely."""

TEARDOWN_CACHE_HEADER = "x-milexium-teardown-cache"
"""`hit` | `miss` | `disabled`. A response header, not a response field: the
teardown response body is the `DeadheadTeardown` itself and must stay
byte-identical whether it was computed or replayed -- if caching could change
the body it would be changing the answer, which is the one thing a cache must
never do. Tested as such."""


class _TeardownResultCache:
    """Bounded LRU of serialised teardown responses, keyed by the SHA-256 of the
    raw request body.

    Sound because `teardown_deadhead` is a pure function of its arguments: it
    reads no clock, no store and no randomness, so identical request bytes have
    exactly one correct answer, forever. (`TeardownManifest.teardown_id` and
    `segment_sha256` are the module's own statement of that -- the same export
    torn down the same way pins the same id.) This cache does not make that
    true; it relies on it, and the conformance suite asserts the replayed body
    is byte-identical to a freshly computed one.

    Keyed on the RAW BYTES rather than on `segment_sha256`, deliberately. The
    fingerprint is order-independent and semantically exact, and it is also
    ~50% of the runtime (ADR-0056) and only available after the parse -- keying
    on it would leave the parse and the fingerprint on the warm path and save
    roughly half. Hashing 2.37 MB of raw body costs ~5 ms and skips parse,
    validation, analysis and serialisation alike. The price of that choice is
    that the key is byte-exact: the same segments re-serialised with different
    JSON key order or whitespace MISS. That is a weaker equivalence than the
    teardown's own, and it is the honest trade -- a miss is merely slow, and a
    cache that had to parse before it could look anything up would not be worth
    having.
    """

    def __init__(self, capacity: int) -> None:
        self._capacity = capacity
        self._entries: "OrderedDict[str, tuple[int, str, bytes]]" = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> "tuple[int, str, bytes] | None":
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.misses += 1
                return None
            self._entries.move_to_end(key)
            self.hits += 1
            return entry

    def put(self, key: str, entry: "tuple[int, str, bytes]") -> None:
        with self._lock:
            self._entries[key] = entry
            self._entries.move_to_end(key)
            while len(self._entries) > self._capacity:
                self._entries.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


class _TeardownRoute(APIRoute):
    """Wraps `POST /teardowns` with the two things that have to happen BEFORE
    FastAPI validates the body, and therefore cannot live in the handler.

    A route class, not middleware and not a handler change, for one reason: the
    handler's declared body model is what generates the OpenAPI schema, and that
    schema is the refusal surface (`is_guaranteed_saving` and `causal_proof` are
    absent from `TeardownRequest`, and `additionalProperties: false` says so to
    every generated client). Reading the raw body inside the handler is
    impossible -- validation has already happened -- and taking a bare `Request`
    to get at it would delete the schema. This wrapper sees the raw bytes and
    leaves the contract untouched; `contracts/openapi/milexium-api-v0.1.json` is
    unchanged by it, which the drift gate proves rather than asserts.

    WHY NOT AN ASYNC JOB + POLL, which is the obvious answer:

    1. **It would need auth this app does not have.** A job id handed back for
       later collection is a bearer token over an operator's operational data,
       and this app documents that it has no credential check and no per-request
       tenant resolution. Async submission would be the first endpoint here to
       create a server-side artifact someone else could ask for.
    2. **It would not be async.** The teardown is CPU-bound Python holding the
       GIL. A `BackgroundTask` or a bare `asyncio` hop runs it on the same event
       loop, so the request that "returned immediately" blocks every other
       request for the full duration -- strictly worse than blocking one caller.
       A real async path needs a process pool or a queue, which is
       infrastructure this slice does not have and should not fake.
    3. **The accepted path is 1.5-2.0 s, not 46 s.** `MAX_TEARDOWN_SEGMENTS`
       already bounds it. Building job submission, status polling, result
       collection and expiry to move a ~2 s call off the request thread would be
       a large amount of new state for a latency that is not the defect. The
       defect was a 31 s refusal and an uncached repeat, and both are fixed here
       without any state that outlives a request.

    None of that says async is wrong. It says async needs auth, a worker pool
    and a result store first, and this surface has none of the three. When it
    does, the SDK's unbounded path -- which is where ADR-0056's 46 s actually
    lives -- is the thing it should be built for.

    Streaming/progress was rejected on simpler grounds: a teardown produces its
    answer only at the end, so there is nothing to stream but a spinner.
    """

    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        original = super().get_route_handler()

        async def guarded_and_cached(request: Request) -> Response:
            # (1) Refuse on size before reading the stream. `content-length` is
            # advisory, so the same bound is re-checked against the bytes we
            # actually received; a chunked upload with no header is caught there.
            declared = request.headers.get("content-length")
            if declared is not None and declared.isdigit():
                _refuse_oversize_body(int(declared), measured=False)
            body = await request.body()
            _refuse_oversize_body(len(body), measured=True)

            cache: _TeardownResultCache | None = getattr(
                request.app.state, "teardown_cache", None
            )
            if cache is None:
                response = await original(request)
                response.headers[TEARDOWN_CACHE_HEADER] = "disabled"
                return response

            key = hashlib.sha256(body).hexdigest()
            cached = cache.get(key)
            if cached is not None:
                status_code, media_type, payload = cached
                return Response(
                    content=payload,
                    status_code=status_code,
                    media_type=media_type,
                    headers={TEARDOWN_CACHE_HEADER: "hit"},
                )

            response = await original(request)
            # A refusal is never cached, and the mechanism is worth stating
            # precisely because it is not this `if`. Every non-200 on this route
            # -- the count 413, a 422 from validation, the size 413 above -- is
            # RAISED, and Starlette's exception middleware sits outside this
            # wrapper, so a refusal never reaches this line at all and never
            # gets the cache header either. The status check below is therefore
            # a belt on top of braces: it is what would still hold the line if
            # someone later made this route return an error Response instead of
            # raising one. (Which is worth holding: a 413 depends on limits a
            # redeploy can legitimately change, so replaying one would replay a
            # refusal that may no longer be true.)
            payload = getattr(response, "body", None)
            if response.status_code == 200 and isinstance(payload, bytes):
                cache.put(key, (response.status_code, response.media_type or "", payload))
            response.headers[TEARDOWN_CACHE_HEADER] = "miss"
            return response

        return guarded_and_cached


def _refuse_oversize_body(size: int, *, measured: bool) -> None:
    if size <= MAX_TEARDOWN_BODY_BYTES:
        return
    seen = "received" if measured else "declared in content-length"
    raise HTTPException(
        status_code=413,
        detail=(
            f"request body is {size:,} bytes ({seen}), above this endpoint's ceiling of "
            f"{MAX_TEARDOWN_BODY_BYTES:,}. It was refused WITHOUT being parsed: the "
            "segment-count check further in costs a full validation pass over every "
            "segment, so a body this size would have spent tens of seconds of server "
            f"time to produce this same refusal. The segment ceiling is "
            f"{MAX_TEARDOWN_SEGMENTS:,}; split the request by observation window, or "
            "drive MilexiumClient.teardown_deadhead, which has no ceiling but IS "
            "synchronous -- MilexiumClient.estimate_teardown_seconds(n) says roughly "
            "what that will cost before you commit to waiting for it."
        ),
    )


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


def create_app(
    client: MilexiumClient | None = None,
    *,
    teardown_cache_entries: int = DEFAULT_TEARDOWN_CACHE_ENTRIES,
) -> FastAPI:
    """Build the app over a `MilexiumClient`. The client is injectable so tests
    (and a real deployment swapping the in-memory store for a Postgres-backed
    one) can supply their own; the default is a single in-memory tenant.

    `teardown_cache_entries=0` disables the teardown result cache. The cache is
    per-app, not module-global, so two apps in one process never share one and a
    test measuring the COLD path can ask for an app that has none.
    """
    client = client or in_memory_client()

    app = FastAPI(title="Milexium API", version=API_VERSION, description=__doc__)
    app.state.client = client
    app.state.teardown_cache = (
        _TeardownResultCache(teardown_cache_entries) if teardown_cache_entries > 0 else None
    )

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

    # The teardown endpoint alone gets `_TeardownRoute` -- the pre-parse size
    # guard and the result cache are wrong for the other endpoints (nothing else
    # here is expensive enough to be worth caching, and a cache in front of a
    # store-reading endpoint would serve stale reads). Routed rather than
    # decorated because a route class is per-router in FastAPI; the path,
    # operation id, tags and schemas are identical either way, which the
    # contract-drift gate checks.
    teardown_router = APIRouter(route_class=_TeardownRoute)

    @teardown_router.post("/teardowns", response_model=DeadheadTeardown, tags=["teardown"])
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
        because anything is created server-side. An identical repeat request may
        be answered from `_TeardownResultCache` rather than recomputed -- the
        response body is byte-identical either way, and
        `x-milexium-teardown-cache` says which happened.
        """
        if len(body.segments) > MAX_TEARDOWN_SEGMENTS:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"{len(body.segments)} segments exceeds this endpoint's ceiling of "
                    f"{MAX_TEARDOWN_SEGMENTS}. The teardown is not truncated to fit, because a "
                    "truncated teardown understates every total it reports; split the request by "
                    "observation window, or drive MilexiumClient.teardown_deadhead, which has no "
                    "ceiling but IS synchronous -- ADR-0056 measured a mid-size operator's YEAR "
                    "at ~46-55 s, so call MilexiumClient.estimate_teardown_seconds(n) first "
                    "rather than discovering the wait by waiting."
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

    app.include_router(teardown_router)
    return app


app = create_app()
