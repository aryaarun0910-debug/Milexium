"""Conformance for the Program M depth slice: the deadhead teardown and the
operator-export intake check reachable WITHOUT writing Python.

Two capabilities a design partner actually asks for by name were, until this
packet, reachable only by importing a module: `aletheia.replay.teardown`
(ADR-0039) and `themis.connect.operator_export` (ADR-0038). They are now on
the SDK facade and over HTTP, and the whole question this file answers is
whether their REFUSALS survived the trip.

What is being defended, in order of how badly it would matter if it broke:

1. The teardown's hedging reaches the HTTP response. `causal_proof` is False,
   `is_modelled` is True, the modelled/not-a-saving wording is in the body, and
   no endpoint accepts a parameter that would claim otherwise.
2. The intake check never echoes a rejected identifier's VALUE. It names the
   offending column so the agency can strip it, and returns nothing else about
   it -- not even the adapter's own (already redacted) quarantine record.
3. The intake check persists nothing, proved by counting every row in every
   table of the app's store before and after the request.

EVERY FIXTURE HERE IS SYNTHETIC. No operator has sent Milexium any data. The
"rider name" and "email" values below were written for this file to be rejected
by; they describe nobody.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from argus.api.app import (
    MAX_TEARDOWN_SEGMENTS,
    MAX_VALIDATION_ROWS,
    create_app,
    in_memory_client,
)
from aletheia.replay.teardown import (
    DEADHEAD_TEARDOWN_NOTE,
    FIXED_COST_HEDGE,
    DeadheadTeardown,
    VehicleSegment,
)
from argus.sdk import MilexiumClient


def _client() -> TestClient:
    return TestClient(create_app())


# --- SYNTHETIC segment fixtures ---------------------------------------------
#
# One imagined vehicle's morning: two revenue trips with an empty reposition
# between them, plus one unattributed empty leg (the export did not say which
# run it belonged to). Deliberately crosses an hour boundary (08:50 -> 09:10)
# so the boundary-splitting behaviour is exercised over the wire too.

SEGMENTS: list[dict] = [
    {
        "started_at": "2026-03-04T08:00:00Z",
        "ended_at": "2026-03-04T08:50:00Z",
        "kind": "revenue",
        "run_ref": "RUN-A",
    },
    {
        "started_at": "2026-03-04T08:50:00Z",
        "ended_at": "2026-03-04T09:10:00Z",
        "kind": "deadhead",
        "run_ref": "RUN-A",
    },
    {
        "started_at": "2026-03-04T09:10:00Z",
        "ended_at": "2026-03-04T09:40:00Z",
        "kind": "revenue",
        "run_ref": "RUN-B",
    },
    {
        "started_at": "2026-03-04T09:40:00Z",
        "ended_at": "2026-03-04T10:00:00Z",
        "kind": "deadhead",
        "run_ref": None,
    },
]

TEARDOWN_BODY: dict = {
    "segments": SEGMENTS,
    "dataset_label": "synthetic fixture, aletheia/conformance/property-tests/test_api_teardown.py",
    "data_provenance": "synthetic",
    "run_ref_source": "run_ref (synthetic)",
}


def _segments() -> list[VehicleSegment]:
    return [VehicleSegment.model_validate(s) for s in SEGMENTS]


# ---------------------------------------------------------------------------
# 1. The SDK facade: one import drives the teardown
# ---------------------------------------------------------------------------


def test_teardown_round_trips_through_the_sdk_facade() -> None:
    """A caller holding only `MilexiumClient` can run a teardown and gets the
    real structured answer -- not a stub, not a re-implementation."""

    client = MilexiumClient.in_memory(tenant_name="Teardown SDK tenant")
    result = client.teardown_deadhead(
        _segments(),
        dataset_label="synthetic fixture",
        data_provenance="synthetic",
        run_ref_source="run_ref (synthetic)",
    )

    assert isinstance(result, DeadheadTeardown)
    assert result.total_deadhead_minutes == 40.0  # 20 attributed + 20 unattributable
    assert result.total_revenue_minutes == 80.0
    assert result.attributed_run_count == 1
    assert result.top_runs[0].run_ref == "RUN-A"
    assert result.unattributable is not None
    assert result.unattributable.deadhead_minutes == 20.0

    # The hour-boundary split reconciles: the 08:50->09:10 empty leg contributes
    # 10 minutes to hour 08 and 10 to hour 09, not 20 to either. Hour 09 then
    # also takes the whole 09:40->10:00 unattributed leg, so 10 + 20 = 30.
    by_hour = {b.hour_of_day: b.deadhead_minutes for b in result.by_hour_of_day}
    assert by_hour[8] == 10.0 and by_hour[9] == 30.0
    assert sum(b.deadhead_minutes for b in result.by_hour_of_day) == result.total_deadhead_minutes


def test_the_sdk_teardown_is_the_same_answer_the_http_endpoint_gives() -> None:
    """The facade and the endpoint are one implementation, not two: the
    deterministic teardown_id pins that."""

    client = MilexiumClient.in_memory(tenant_name="Parity tenant")
    direct = client.teardown_deadhead(
        _segments(),
        dataset_label=TEARDOWN_BODY["dataset_label"],
        data_provenance="synthetic",
        run_ref_source=TEARDOWN_BODY["run_ref_source"],
    )
    over_http = _client().post("/teardowns", json=TEARDOWN_BODY).json()
    assert over_http["manifest"]["teardown_id"] == direct.manifest.teardown_id


def test_the_sdk_teardown_writes_nothing_to_the_store() -> None:
    """A teardown is a value, not a stored artifact. Recording one is an
    explicit `record_decision`, never a side effect of analysing."""

    client = MilexiumClient.in_memory(tenant_name="Stateless tenant")
    before = _row_counts(client)
    client.teardown_deadhead(
        _segments(),
        dataset_label="synthetic fixture",
        data_provenance="synthetic",
        run_ref_source="run_ref (synthetic)",
    )
    assert _row_counts(client) == before


# ---------------------------------------------------------------------------
# 2. The teardown over HTTP -- and the refusals that must survive the boundary
# ---------------------------------------------------------------------------


def test_teardown_endpoint_returns_the_structured_answer() -> None:
    response = _client().post("/teardowns", json=TEARDOWN_BODY)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["total_deadhead_minutes"] == 40.0
    assert body["total_revenue_minutes"] == 80.0
    assert body["unattributable"]["deadhead_minutes"] == 20.0
    assert body["unattributable"]["attributable"] is False
    assert body["manifest"]["segment_count"] == 4
    assert body["manifest"]["data_provenance"] == "synthetic"

    # The response validates back into the domain model -- the wire shape is the
    # real thing, not a lossy projection of it.
    assert DeadheadTeardown.model_validate(body).manifest.teardown_id == body["manifest"]["teardown_id"]


def test_modelled_and_hedged_wording_reaches_the_http_response() -> None:
    """The words are the product boundary (ADR-0019 / blueprint/01). If the API
    can return a teardown without them, the API is the weak link."""

    body = _client().post("/teardowns", json=TEARDOWN_BODY).json()

    assert body["is_modelled"] is True
    assert body["causal_proof"] is False
    assert body["interpretation"] == DEADHEAD_TEARDOWN_NOTE
    assert body["manifest"]["note"] == DEADHEAD_TEARDOWN_NOTE
    assert "not causal proof" in body["interpretation"]
    assert "not a promised saving" in body["interpretation"]
    # The replay discipline note travels too, so the teardown cannot be read
    # apart from the comparison framing it inherits.
    assert body["manifest"]["replay_discipline_note"]


def test_cost_hedge_and_the_refusal_to_invent_a_recovery_rate_survive_http() -> None:
    """With a rate but no fixed-versus-variable split: a value, an explicit
    absence of an envelope, and the hedge -- never a saving."""

    body = dict(
        TEARDOWN_BODY,
        cost_basis={
            "cost_per_vehicle_hour": 76.885,
            "source": "SYNTHETIC stand-in rate for this test, not an agency figure",
        },
    )
    cost = _client().post("/teardowns", json=body).json()["cost"]

    assert cost["value_at_full_cost"] == 51.256667  # (40/60)h x 76.885
    assert cost["modelled_envelope_low"] is None
    assert cost["modelled_envelope_high"] is None
    assert "is not guessed" in cost["envelope_basis"]
    assert cost["is_guaranteed_saving"] is False
    assert cost["hedge"] == FIXED_COST_HEDGE


def test_supplying_the_split_produces_an_envelope_still_labelled_not_cash() -> None:
    body = dict(
        TEARDOWN_BODY,
        cost_basis={
            "cost_per_vehicle_hour": 76.885,
            "source": "SYNTHETIC stand-in rate for this test, not an agency figure",
            "avoidable_share_low": 0.3,
            "avoidable_share_high": 0.5,
        },
    )
    cost = _client().post("/teardowns", json=body).json()["cost"]

    assert cost["modelled_envelope_low"] is not None
    assert cost["modelled_envelope_high"] > cost["modelled_envelope_low"]
    assert cost["modelled_envelope_high"] < cost["value_at_full_cost"]
    assert "not guaranteed cash" in cost["hedge"]


def test_no_endpoint_accepts_a_guaranteed_saving_or_causal_proof_parameter() -> None:
    """The strongest form of the invariant: not "it is ignored", but "the
    request is refused". `extra="forbid"` on the body makes it a 422."""

    c = _client()
    for forbidden in (
        {"is_guaranteed_saving": True},
        {"causal_proof": True},
        {"guaranteed_saving_usd": 1000},
        {"is_modelled": False},
    ):
        response = c.post("/teardowns", json=dict(TEARDOWN_BODY, **forbidden))
        assert response.status_code == 422, f"{forbidden} was not refused: {response.text}"

    # The same refusal one level down, inside the cost basis.
    nested = c.post(
        "/teardowns",
        json=dict(
            TEARDOWN_BODY,
            cost_basis={
                "cost_per_vehicle_hour": 50.0,
                "source": "SYNTHETIC",
                "is_guaranteed_saving": True,
            },
        ),
    )
    assert nested.status_code == 422


def test_operator_provenance_cannot_be_claimed_over_http() -> None:
    """There is no operator data in this repo, so `DataProvenance` has no
    "operator" value -- and an HTTP caller cannot mint one either."""

    response = _client().post(
        "/teardowns", json=dict(TEARDOWN_BODY, data_provenance="operator")
    )
    assert response.status_code == 422


def test_segment_construction_rules_are_enforced_on_the_wire() -> None:
    c = _client()

    # A rider identifier cannot be attached to a segment (extra="forbid").
    with_rider = dict(SEGMENTS[0], rider_name="SYNTHETIC Jane Doe")
    assert c.post("/teardowns", json=dict(TEARDOWN_BODY, segments=[with_rider])).status_code == 422

    # A naive timestamp is refused, not assumed to be UTC.
    naive = dict(SEGMENTS[0], started_at="2026-03-04T08:00:00")
    assert c.post("/teardowns", json=dict(TEARDOWN_BODY, segments=[naive])).status_code == 422

    # Backwards, and the 48h parsing-artefact ceiling.
    backwards = dict(SEGMENTS[0], ended_at="2026-03-04T07:00:00Z")
    assert c.post("/teardowns", json=dict(TEARDOWN_BODY, segments=[backwards])).status_code == 422
    too_long = dict(SEGMENTS[0], ended_at="2026-03-09T08:00:00Z")
    assert c.post("/teardowns", json=dict(TEARDOWN_BODY, segments=[too_long])).status_code == 422

    # An out-of-range modelling assumption is refused rather than clamped.
    assert (
        c.post("/teardowns", json=dict(TEARDOWN_BODY, reduction_fraction=1.5)).status_code == 422
    )


def test_an_oversize_teardown_is_refused_rather_than_truncated() -> None:
    """Truncating would understate every total the answer reports, which is
    worse than refusing."""

    one = SEGMENTS[0]
    response = _client().post(
        "/teardowns",
        json=dict(TEARDOWN_BODY, segments=[one] * (MAX_TEARDOWN_SEGMENTS + 1)),
    )
    assert response.status_code == 413
    assert "MilexiumClient.teardown_deadhead" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 3. The intake validation endpoint
# ---------------------------------------------------------------------------
#
# SYNTHETIC rows. The PII row's values exist to be rejected and describe nobody.

CLEAN_ROW = {
    "trip_ref": "T-0001",
    "requested_at": "2026-03-02T19:05:00+00:00",
    "scheduled_pickup_at": "2026-03-04T13:15:00+00:00",
    "actual_pickup_at": "2026-03-04T13:22:00+00:00",
    "pickup_zone": "NW3",
    "dropoff_zone": "CBD1",
    "run_ref": "RUN-A",
    "outcome": "served",
}

RIDER_NAME_VALUE = "SYNTHETIC-NOBODY-Jane-Q-Doe"
RIDER_EMAIL_VALUE = "synthetic-nobody@example.invalid"

PII_ROW = dict(CLEAN_ROW, trip_ref="T-0002", rider_name=RIDER_NAME_VALUE)
HIDDEN_EMAIL_ROW = dict(CLEAN_ROW, trip_ref="T-0003", contact_1=RIDER_EMAIL_VALUE)
INCOMPLETE_ROW = dict(CLEAN_ROW, trip_ref="T-0004", outcome="")


def test_validation_endpoint_reports_which_rows_would_quarantine_and_why() -> None:
    response = _client().post(
        "/operator-exports/validate",
        json={"rows": [CLEAN_ROW, PII_ROW, INCOMPLETE_ROW]},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["rows_checked"] == 3
    assert body["accepted"] == 1
    assert body["quarantined"] == 2
    assert body["pii_rejected"] == 1

    clean, pii, incomplete = body["results"]
    assert clean["accepted"] is True and clean["reason"] is None
    # An accepted row still reports what did not map cleanly.
    assert {note["disposition"] for note in clean["semantic_loss"]} <= {
        "dropped",
        "truncated",
        "coerced",
        "unmapped_extension",
    }

    assert pii["accepted"] is False
    assert pii["pii_rejection"] is True
    assert pii["pii_columns"] == ["rider_name"]
    assert "rider_name" in pii["reason"]
    assert "OPERATOR_DATA_INTAKE" in pii["reason"]

    assert incomplete["accepted"] is False
    assert incomplete["pii_rejection"] is False
    assert "outcome" in incomplete["reason"]


def test_a_pii_quarantine_never_echoes_the_offending_value() -> None:
    """The whole point of a pre-flight check is that an agency can point it at a
    real extract. The response names the COLUMN to strip and returns no value
    from it -- not the adapter's redacted quarantine record either."""

    response = _client().post(
        "/operator-exports/validate",
        json={"rows": [PII_ROW, HIDDEN_EMAIL_ROW]},
    )
    raw_body = response.text
    body = response.json()

    assert body["pii_rejected"] == 2

    # The column name is reported (actionable); the value is nowhere in the
    # response at all -- checked against the raw bytes, not a parsed subset.
    assert body["results"][0]["pii_columns"] == ["rider_name"]
    assert RIDER_NAME_VALUE not in raw_body
    assert "Jane" not in raw_body

    # An email hidden in a value under an innocuous column name is caught by the
    # adapter, reported by column, and likewise never quoted back.
    assert body["results"][1]["pii_columns"] == ["contact_1"]
    assert RIDER_EMAIL_VALUE not in raw_body
    assert "@example.invalid" not in raw_body

    # No route to the raw row at all: the response model has no such field.
    assert "raw_row" not in raw_body


def test_the_validation_response_carries_no_source_values_at_all() -> None:
    """Semantic-loss notes are projected without `source_value`. The adapter
    already nulls it wherever personal data could hide; dropping the field means
    that guarantee cannot be undone from the adapter side later."""

    body = _client().post("/operator-exports/validate", json={"rows": [CLEAN_ROW]}).json()
    notes = body["results"][0]["semantic_loss"]
    assert notes
    for note in notes:
        assert set(note) == {"source_field", "disposition", "reason"}


def test_the_validation_endpoint_persists_nothing() -> None:
    """Proved by counting every row in every table of the app's store, before
    and after -- not by trusting the endpoint's own docstring."""

    app = create_app()
    c = TestClient(app)
    client = app.state.client

    before = _row_counts(client)
    response = c.post(
        "/operator-exports/validate",
        json={"rows": [CLEAN_ROW, PII_ROW, INCOMPLETE_ROW]},
    )
    assert response.status_code == 200
    assert _row_counts(client) == before

    # And the response says so, structurally.
    assert response.json()["persisted"] is False
    assert "Nothing from this request was stored" in response.json()["persistence_note"]

    # The tenant the rows were parsed against belongs to no store: the app's own
    # tenant recorded nothing, and no second tenant appeared.
    assert client.store.raw_rows_for_tenant(client.tenant_id) == []


def test_a_column_map_lets_an_agency_check_its_own_header() -> None:
    """The friction forge/knowledge/docs/OPERATOR_DATA_INTAKE.md describes is "will my extract
    be accepted" -- answerable here without sending real data."""

    vendor_row = {
        "BookingNo": "BK-1",
        "Booked On": "2026-03-02T14:05:00-05:00",
        "PromisedPickup": "2026-03-04T08:15:00-05:00",
        "ActualPickup": "2026-03-04T08:22:00-05:00",
        "PU Zone": "ZONE-NW-3",
        "DO Zone": "ZONE-CBD-1",
        "UnitNo": "UNIT-412",
        "TripStatus": "Completed",
    }
    column_map = {
        "BookingNo": "trip_ref",
        "Booked On": "requested_at",
        "PromisedPickup": "scheduled_pickup_at",
        "ActualPickup": "actual_pickup_at",
        "PU Zone": "pickup_zone",
        "DO Zone": "dropoff_zone",
        "UnitNo": "vehicle_ref",
        "TripStatus": "outcome",
    }
    body = _client().post(
        "/operator-exports/validate",
        json={"rows": [vendor_row], "column_map": column_map},
    ).json()
    assert body["accepted"] == 1

    # Without the map the same row is unrecognisable -- which is the answer the
    # agency needs BEFORE sending a full extract, not after.
    unmapped = _client().post("/operator-exports/validate", json={"rows": [vendor_row]}).json()
    assert unmapped["accepted"] == 0


def test_an_unusable_column_map_is_refused_not_guessed() -> None:
    response = _client().post(
        "/operator-exports/validate",
        json={"rows": [CLEAN_ROW], "column_map": {"BookingNo": "not_a_canonical_column"}},
    )
    assert response.status_code == 422


def test_the_validation_endpoint_publishes_the_target_schema_and_pii_categories() -> None:
    """So the agency can act on the verdict without a second document."""

    body = _client().post("/operator-exports/validate", json={"rows": []}).json()
    assert "trip_ref" in body["canonical_columns"]
    assert "personal name" in body["pii_categories"]
    assert body["rows_checked"] == 0


def test_an_oversize_sample_is_refused() -> None:
    response = _client().post(
        "/operator-exports/validate",
        json={"rows": [CLEAN_ROW] * (MAX_VALIDATION_ROWS + 1)},
    )
    assert response.status_code == 413


# ---------------------------------------------------------------------------
# 4. The contract
# ---------------------------------------------------------------------------


def test_openapi_documents_the_two_new_endpoints() -> None:
    spec = _client().get("/openapi.json").json()
    assert "/teardowns" in spec["paths"]
    assert "/operator-exports/validate" in spec["paths"]
    assert "DeadheadTeardown" in spec["components"]["schemas"]
    assert "OperatorExportValidationResponse" in spec["components"]["schemas"]

    # The teardown request schema is the refusal surface: a generated client in
    # any language must see that these fields do not exist.
    request_schema = spec["components"]["schemas"]["TeardownRequest"]
    assert request_schema["additionalProperties"] is False
    assert "is_guaranteed_saving" not in request_schema["properties"]
    assert "causal_proof" not in request_schema["properties"]

    # And the published contract offers no operator provenance to claim: a
    # generated client in any language gets a two-value enum.
    assert request_schema["properties"]["data_provenance"]["enum"] == [
        "real_public",
        "synthetic",
    ]


def test_an_injected_client_serves_the_new_endpoints_too() -> None:
    app = create_app(client=in_memory_client(tenant_name="Injected teardown tenant"))
    c = TestClient(app)
    assert c.post("/teardowns", json=TEARDOWN_BODY).status_code == 200
    assert c.post("/operator-exports/validate", json={"rows": [CLEAN_ROW]}).status_code == 200


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _row_counts(client: MilexiumClient) -> dict[str, int]:
    """Every row in every table of the client's store.

    Reaches the sqlite connection through the store escape hatch on purpose: a
    non-persistence claim checked only through the store's own read methods
    would miss a write to a table those methods do not read.
    """
    conn = client.store._conn
    tables = [
        name
        for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]
    return {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables
    }
