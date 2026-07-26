"""Conformance for the teardown latency defect ADR-0056 recorded and left open.

ADR-0056 measured `app/replay/teardown.py` across 40k->5M segments, found
per-segment cost flat (31-92 us, no upward trend), and concluded the fix is
"caching or async, not a language". It also recorded, as a finding it was not
looking for, that the teardown is reachable from the HTTP/SDK surface and that
~46 s is "a fine batch job and an unacceptable interactive one".

Measuring the SURFACE (not the analysis) relocated the defect. On this machine,
POST /teardowns:

    20,000 segments (the endpoint ceiling)   1.53 s   -- never was 46 s
    600,000 segments -> 413                 31.27 s   -- computing NOTHING

The accepted path was already bounded by `MAX_TEARDOWN_SEGMENTS`. The REFUSAL
was not: the count is only knowable after FastAPI has validated every segment,
so an oversize request paid a full validation pass and then got told no. A
600k-segment body is the top of ADR-0056's own "mid-size operator's year" band --
the exact request that ADR invites an operator to try.

So this file defends three things, in the order they would hurt:

1. **The cache cannot change the answer.** A replayed response is byte-identical
   to a computed one, a changed body is never served a stale one, and a refusal
   is never cached. If caching could alter a teardown it would be altering an
   audit artifact, which is worse than being slow.
2. **The oversize refusal happens BEFORE parsing.** Proved structurally, not by
   a stopwatch: a body that is both oversize AND syntactically unparseable comes
   back 413 (size), not 422 (parse). Only a guard that ran first can do that.
   ADR-0056 is itself a warning about trusting wall-clock on this hardware, so
   the ordering claim is made in a way that does not depend on it.
3. **The SDK's cost is knowable before it is paid.**
   `MilexiumClient.estimate_teardown_seconds` brackets every rung of ADR-0056's
   published ladder, so the estimate and the evidence cannot silently diverge.

The one timing assertion in this file (`..._is_cheaper_than_merely_parsing_it`)
is a RATIO between two operations on the same machine in the same process, with
a ~33x margin, not an absolute bound. That is the only shape of timing claim
this hardware supports.

EVERY FIXTURE HERE IS SYNTHETIC -- generated segments over an imagined fleet.
No operator has sent Milexium any data.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.app import (
    DEFAULT_TEARDOWN_CACHE_ENTRIES,
    MAX_TEARDOWN_BODY_BYTES,
    MAX_TEARDOWN_SEGMENTS,
    TEARDOWN_CACHE_HEADER,
    create_app,
)
from app.sdk import TEARDOWN_MICROSECONDS_PER_SEGMENT, MilexiumClient

_BASE = datetime(2026, 3, 2, 5, 0, tzinfo=timezone.utc)


def _segments(count: int, *, run_refs: int = 400, label: str = "RUN") -> list[dict]:
    """`count` back-to-back 20-minute segments alternating revenue/deadhead.

    Synthetic. The shape matters (hour boundaries get crossed, run references
    repeat) but no value here describes anything real.
    """
    rows: list[dict] = []
    cursor = _BASE
    for i in range(count):
        end = cursor + timedelta(minutes=20)
        rows.append(
            {
                "started_at": cursor.isoformat().replace("+00:00", "Z"),
                "ended_at": end.isoformat().replace("+00:00", "Z"),
                "kind": "revenue" if i % 2 else "deadhead",
                "run_ref": f"{label}-{i % run_refs:04d}",
            }
        )
        cursor = end
    return rows


def _body(count: int, **overrides: object) -> dict:
    body: dict = {
        "segments": _segments(count),
        "dataset_label": "synthetic fixture, test_api_teardown_latency.py",
        "data_provenance": "synthetic",
        "run_ref_source": "run_ref (synthetic)",
    }
    body.update(overrides)
    return body


def _post(client: TestClient, body: dict | str):
    raw = body if isinstance(body, str) else json.dumps(body)
    return client.post("/teardowns", content=raw, headers={"content-type": "application/json"})


# ---------------------------------------------------------------------------
# 1. The cache must never change the answer
# ---------------------------------------------------------------------------


def test_a_replayed_teardown_is_byte_identical_to_a_computed_one() -> None:
    """The load-bearing cache property. A teardown is an audit artifact carrying
    a deterministic `teardown_id`; if the cached copy differed from the computed
    one by so much as a byte, the endpoint would be answering two different
    things to the same question."""

    client = TestClient(create_app())
    body = _body(60)

    first = _post(client, body)
    second = _post(client, body)

    assert first.status_code == second.status_code == 200
    assert first.headers[TEARDOWN_CACHE_HEADER] == "miss"
    assert second.headers[TEARDOWN_CACHE_HEADER] == "hit"
    assert first.content == second.content
    # ...and it is a real teardown, not an empty body agreeing with itself.
    payload = second.json()
    assert payload["total_deadhead_minutes"] > 0
    assert payload["manifest"]["segment_count"] == 60
    assert payload["causal_proof"] is False


def test_a_changed_body_is_never_served_a_cached_answer() -> None:
    """The anti-vacuity test for the key. A cache that returned its one entry
    for everything would pass every test above this one."""

    client = TestClient(create_app())
    small, large = _body(20), _body(40)

    first = _post(client, small)
    other = _post(client, large)
    again = _post(client, small)

    assert first.headers[TEARDOWN_CACHE_HEADER] == "miss"
    assert other.headers[TEARDOWN_CACHE_HEADER] == "miss"
    assert again.headers[TEARDOWN_CACHE_HEADER] == "hit"
    assert first.content == again.content
    assert other.content != first.content
    assert other.json()["manifest"]["segment_count"] == 40
    assert first.json()["manifest"]["segment_count"] == 20


def test_a_modelling_parameter_is_part_of_the_cache_key() -> None:
    """Identical segments, different `reduction_fraction`, different envelope.
    Keying on the segments alone -- the tempting shortcut, since the teardown
    already computes `segment_sha256` over exactly those -- would serve one
    operator's cost envelope for another's assumptions."""

    client = TestClient(create_app())
    cost = {
        "cost_per_vehicle_hour": 92.5,
        "currency": "USD",
        "source": "synthetic",
        "avoidable_share_low": 0.2,
        "avoidable_share_high": 0.5,
    }
    conservative = _body(30, cost_basis=cost, reduction_fraction=0.1)
    aggressive = _body(30, cost_basis=cost, reduction_fraction=0.4)

    a = _post(client, conservative)
    b = _post(client, aggressive)

    assert a.headers[TEARDOWN_CACHE_HEADER] == "miss"
    assert b.headers[TEARDOWN_CACHE_HEADER] == "miss"
    assert a.json()["cost"]["modelled_envelope_high"] != b.json()["cost"]["modelled_envelope_high"]


def test_a_refusal_is_never_cached() -> None:
    """A 413 depends on limits a redeploy can legitimately change, so replaying
    one would be replaying a refusal that may no longer hold.

    Asserts the MECHANISM, not just the outcome. Every refusal on this route is
    raised, and Starlette's exception middleware sits outside the caching
    wrapper, so a refusal never reaches the store branch -- which is observable
    as the ABSENCE of the cache header. Checking only `len(cache) == 0` passed
    even when the store branch was mutated to accept 413s, because the branch is
    unreachable for a refusal; the header assertion is what makes this test able
    to fail if someone starts catching those exceptions and caching them.
    """

    app = create_app()
    client = TestClient(app)
    over = _body(MAX_TEARDOWN_SEGMENTS + 1)
    oversize = "{" + "x" * (MAX_TEARDOWN_BODY_BYTES + 1)

    for attempt in (_post(client, over), _post(client, over), _post(client, oversize)):
        assert attempt.status_code == 413
        assert TEARDOWN_CACHE_HEADER not in attempt.headers, (
            "a refusal reached the caching wrapper's success path"
        )
    assert len(app.state.teardown_cache) == 0

    # ...and the endpoint is not simply refusing everything: a legal body still
    # answers, and still caches.
    assert _post(client, _body(10)).status_code == 200
    assert len(app.state.teardown_cache) == 1


def test_the_cache_is_bounded_and_evicts_the_oldest_entry() -> None:
    """An unbounded cache on an endpoint with no auth and no quota is a
    memory-growth primitive for anyone who can reach it."""

    app = create_app(teardown_cache_entries=3)
    client = TestClient(app)

    bodies = [_body(10, dataset_label=f"synthetic fixture {i}") for i in range(4)]
    for body in bodies:
        assert _post(client, body).headers[TEARDOWN_CACHE_HEADER] == "miss"

    assert len(app.state.teardown_cache) == 3
    # The oldest was evicted; the newest is still resident.
    assert _post(client, bodies[0]).headers[TEARDOWN_CACHE_HEADER] == "miss"
    assert _post(client, bodies[3]).headers[TEARDOWN_CACHE_HEADER] == "hit"


def test_the_cache_can_be_turned_off_entirely() -> None:
    """So a deployment that will not tolerate results held in memory, and a test
    that wants to measure the COLD path, can both say so."""

    app = create_app(teardown_cache_entries=0)
    client = TestClient(app)
    body = _body(20)

    first, second = _post(client, body), _post(client, body)

    assert app.state.teardown_cache is None
    assert first.status_code == second.status_code == 200
    assert first.headers[TEARDOWN_CACHE_HEADER] == "disabled"
    assert second.headers[TEARDOWN_CACHE_HEADER] == "disabled"
    assert first.content == second.content


def test_two_apps_never_share_a_teardown_cache() -> None:
    """The cache is per-app state, not a module global. A module global would
    leak one process's results between apps -- and between the tests above,
    which would make several of them vacuous."""

    warm, cold = TestClient(create_app()), TestClient(create_app())
    body = _body(20)

    assert _post(warm, body).headers[TEARDOWN_CACHE_HEADER] == "miss"
    assert _post(warm, body).headers[TEARDOWN_CACHE_HEADER] == "hit"
    assert _post(cold, body).headers[TEARDOWN_CACHE_HEADER] == "miss"


def test_the_default_app_has_a_cache_of_the_documented_size() -> None:
    app = create_app()
    assert app.state.teardown_cache is not None
    assert DEFAULT_TEARDOWN_CACHE_ENTRIES > 0
    for i in range(DEFAULT_TEARDOWN_CACHE_ENTRIES + 2):
        _post(TestClient(app), _body(5, dataset_label=f"synthetic fixture {i}"))
    assert len(app.state.teardown_cache) == DEFAULT_TEARDOWN_CACHE_ENTRIES


# ---------------------------------------------------------------------------
# 2. The oversize refusal must happen before the parse
# ---------------------------------------------------------------------------


def test_an_oversize_body_is_refused_without_being_parsed() -> None:
    """The ordering proof, made WITHOUT a stopwatch.

    The body is oversize AND syntactically broken. A guard that runs before
    parsing answers 413 (too large). A guard that runs after parsing cannot --
    the parser would have failed first and returned 422. The status code is
    therefore a decision procedure for which one ran, and it does not care how
    fast the machine is.
    """

    client = TestClient(create_app())
    garbage = "{" + "x" * (MAX_TEARDOWN_BODY_BYTES + 1)

    response = _post(client, garbage)

    assert response.status_code == 413, "a post-parse guard would have said 422"
    detail = response.json()["detail"]
    assert "WITHOUT being parsed" in detail
    assert "content-length" in detail


def test_an_oversize_body_with_a_legal_segment_count_is_still_refused() -> None:
    """The byte ceiling is a real second guard, not a restatement of the count
    ceiling. This body has far fewer than `MAX_TEARDOWN_SEGMENTS` segments and is
    refused anyway, because `run_ref` is an unbounded string and 500 legal
    segments can therefore be arbitrarily large. The tradeoff is documented on
    `MAX_TEARDOWN_BODY_BYTES` rather than discovered in production."""

    padding = "R" * (MAX_TEARDOWN_BODY_BYTES // 500 + 64)
    body = _body(0)
    body["segments"] = _segments(500, run_refs=500, label=padding)
    raw = json.dumps(body)
    assert len(raw.encode()) > MAX_TEARDOWN_BODY_BYTES
    assert len(body["segments"]) < MAX_TEARDOWN_SEGMENTS

    response = _post(TestClient(create_app()), raw)

    assert response.status_code == 413
    assert "WITHOUT being parsed" in response.json()["detail"]


def test_a_body_at_the_full_segment_ceiling_is_still_accepted() -> None:
    """The byte ceiling must not have quietly lowered the segment ceiling. This
    is the endpoint's advertised maximum request, and it must still answer 200 --
    the guard is there to refuse the pathological, not to shrink the contract."""

    body = _body(MAX_TEARDOWN_SEGMENTS)
    raw = json.dumps(body)
    assert len(raw.encode()) < MAX_TEARDOWN_BODY_BYTES

    response = _post(TestClient(create_app()), raw)

    assert response.status_code == 200
    assert response.json()["manifest"]["segment_count"] == MAX_TEARDOWN_SEGMENTS


def test_an_oversize_refusal_is_cheaper_than_merely_parsing_the_body() -> None:
    """The only timing claim here, and it is a RATIO on one machine, not a bound.

    Before the guard, an oversize request paid full JSON parsing AND full
    Pydantic validation of every segment before being refused; `json.loads`
    alone is the smaller half of that. If the refusal is not even faster than
    parsing, the guard is not running before the parse.

    Measured margin on the reference machine is ~33x (19 ms vs 630 ms), so the
    2x bound asserted here is loose by more than an order of magnitude -- it will
    not flap on a slow or contended runner, and it still goes red the moment the
    guard moves back behind the parser.
    """

    body = _body(0)
    body["segments"] = _segments(100_000)
    raw = json.dumps(body)
    encoded = raw.encode()
    assert len(encoded) > MAX_TEARDOWN_BODY_BYTES

    client = TestClient(create_app())
    started = time.perf_counter()
    response = _post(client, raw)
    refusal_seconds = time.perf_counter() - started

    started = time.perf_counter()
    json.loads(encoded)
    parse_seconds = time.perf_counter() - started

    assert response.status_code == 413
    assert refusal_seconds < parse_seconds / 2, (
        f"refusal took {refusal_seconds:.3f}s but merely PARSING the same body took "
        f"{parse_seconds:.3f}s -- the guard is not running before the parse"
    )


def test_the_exact_segment_ceiling_still_answers_the_count_message() -> None:
    """A body just over the segment ceiling but under the byte ceiling must
    still get the precise count refusal, not the approximate size one. The two
    guards are ordered cheap-then-exact, and the exact one must survive."""

    response = _post(TestClient(create_app()), _body(MAX_TEARDOWN_SEGMENTS + 1))

    assert response.status_code == 413
    detail = response.json()["detail"]
    assert f"{MAX_TEARDOWN_SEGMENTS + 1} segments exceeds" in detail
    assert "WITHOUT being parsed" not in detail
    # It must not send bulk callers at an unbounded synchronous call without
    # saying what that costs -- the sentence that made ADR-0056's 46 s reachable.
    assert "estimate_teardown_seconds" in detail


# ---------------------------------------------------------------------------
# 3. The contract the route wrapper must not have moved
# ---------------------------------------------------------------------------


def test_the_route_wrapper_left_the_openapi_teardown_contract_intact() -> None:
    """`_TeardownRoute` exists so the raw body can be seen BEFORE validation.
    The reason it is a route class and not a bare `Request` handler is that the
    declared body model generates the schema, and that schema is the refusal
    surface every generated client reads."""

    spec = TestClient(create_app()).get("/openapi.json").json()
    operation = spec["paths"]["/teardowns"]["post"]

    assert operation["operationId"] == "teardown_teardowns_post"
    assert operation["tags"] == ["teardown"]
    ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/TeardownRequest")

    request_schema = spec["components"]["schemas"]["TeardownRequest"]
    assert request_schema["additionalProperties"] is False
    assert "is_guaranteed_saving" not in request_schema["properties"]
    assert "causal_proof" not in request_schema["properties"]
    assert "DeadheadTeardown" in spec["components"]["schemas"]


# ---------------------------------------------------------------------------
# 4. The SDK path: no ceiling, but no longer silent about the cost
# ---------------------------------------------------------------------------

# ADR-0056's published ladder, verbatim: (segments, measured wall seconds).
# The estimator is checked against the evidence it claims to summarise, so the
# two cannot drift apart without a test going red.
ADR_0056_LADDER: tuple[tuple[int, float], ...] = (
    (40_000, 2.80),
    (66_940, 4.14),
    (200_000, 13.66),
    (500_000, 46.09),
    (1_000_000, 76.46),
    (2_000_000, 107.61),
    (5_000_000, 156.54),
)


@pytest.mark.parametrize(("segments", "measured_seconds"), ADR_0056_LADDER)
def test_the_estimate_brackets_every_rung_adr_0056_actually_measured(
    segments: int, measured_seconds: float
) -> None:
    low, high = MilexiumClient.estimate_teardown_seconds(segments)
    assert low <= measured_seconds <= high, (
        f"{segments:,} segments measured {measured_seconds}s in ADR-0056 but the "
        f"estimator says {low:.1f}-{high:.1f}s"
    )


def test_the_estimate_is_a_range_and_never_collapses_to_a_promise() -> None:
    low, high = MilexiumClient.estimate_teardown_seconds(500_000)
    assert low < high
    assert TEARDOWN_MICROSECONDS_PER_SEGMENT[0] < TEARDOWN_MICROSECONDS_PER_SEGMENT[1]
    # ...and it is not a wide-enough-to-be-useless range either: the high end of
    # an operator year has to land in the tens of seconds, which is the number
    # that makes a caller choose to split the request.
    assert 30.0 < high < 120.0


def test_the_estimate_scales_with_the_input_and_is_zero_for_nothing() -> None:
    assert MilexiumClient.estimate_teardown_seconds(0) == (0.0, 0.0)
    small = MilexiumClient.estimate_teardown_seconds(10_000)
    large = MilexiumClient.estimate_teardown_seconds(100_000)
    assert large[0] == pytest.approx(small[0] * 10)
    assert large[1] == pytest.approx(small[1] * 10)


def test_the_estimate_refuses_a_negative_segment_count() -> None:
    """Returning a negative duration would be worse than refusing."""
    with pytest.raises(ValueError, match="must not be negative"):
        MilexiumClient.estimate_teardown_seconds(-1)


def test_the_estimate_is_reachable_without_constructing_a_client() -> None:
    """The 413 message tells a caller to run it before committing to the wait.
    Requiring a store and a tenant just to ask "how long?" would make that
    advice cost more than the question."""
    assert MilexiumClient.estimate_teardown_seconds(1_000)[1] > 0
