"""Conformance: the DURABLE PER-REQUEST LIFECYCLE RECORD (MX-A-LIFECYCLE-RECORD-010).

WHAT SENTENCE THIS FILE HAS TO MAKE TRUE. This repository has told an
accessibility chief, in writing, that it "records why each trip received the
outcome it did -- booked, offered, negotiated, denied or late -- created at the
moment of the decision rather than reconstructed afterwards." Before this packet
the repository had a normative transition TABLE (`state_machine.py`) and an
independent verifier for a history handed to it in memory
(`packages/verify/state_verifier.py`) -- and NO durable per-request history for
either of them to be about. `service_requests` stores what a request currently
looks like, one row per version, and no store method writes it. The sentence was
therefore a claim about a rulebook, described as if it were a record.

WHAT IS UNDER TEST, in order of how badly it would matter if it were wrong:

1. **Decision-time capture, enforced structurally rather than promised.**
   `decided_at` is a required argument with no default; no module on the write
   path reads a clock (asserted by AST over the actual source); the `decided_at`
   COLUMN carries no SQL DEFAULT (read back out of `information_schema`, with a
   positive control proving that query can see a default when one exists); and a
   row whose `recorded_at` precedes its `decided_at` is refused in Python AND by
   a CHECK constraint in the database.
2. **The CHECK is correct, which is not the same as present.** `recorded_at >=
   decided_at` is a TEXT comparison, and on PostgreSQL TEXT compares under the
   database COLLATION, not byte order. On this repository's dev collation the
   repository's own everyday timestamp format compares in the WRONG ORDER across
   the fractional-second boundary. `test_the_collation_would_break_a_naive_timestamp_format`
   demonstrates that on the live server; the fixed-width format is what makes the
   constraint sound, and it is pinned here so it cannot be "simplified" back.
3. **Legality at the RECORD layer.** Every illegal `from -> to` pair is refused by
   the store, exhaustively, on both engines -- and a row forced past the store by
   raw SQL cannot be read back as a record either.
4. **The explain view**: terminal state, the codes that produced it, and the
   negotiated-vs-requested window delta, identical on both engines.

Tenant isolation for this table is the subject of `test_lifecycle_rls.py`, which
proves the DATABASE POLICY rather than the WHERE clauses tested here.

EVERY FIXTURE IN THIS FILE IS SYNTHETIC. No operator lifecycle data exists in
this repository, so the status this evidence can support is **Demonstrated**.
Nothing here is Validated and nothing here should be described as such.

The PostgreSQL parameter skips cleanly (never fails) when the native
`milexium_dev` instance on 5432 is absent, so CI stays green -- but a skip proves
nothing, so the packet's evidence requirement is that these RUN.
"""

from __future__ import annotations

import ast
import inspect
import json
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from packages.canonical.entities import Tenant
from packages.canonical.ids import (
    RequestId,
    RequestTransitionId,
    TenantId,
    new_id,
)
from packages.canonical.lifecycle import (
    BackdatedRecordError,
    LifecycleOrderError,
    RequestTransition,
    TimeWindow,
    iso_fixed_utc,
)
from packages.canonical.postgres_storage import (
    PostgresCanonicalStore,
    is_reachable as pg_is_reachable,
)
from packages.canonical.state_machine import (
    SERVICE_REQUEST_INITIAL_STATE,
    SERVICE_REQUEST_TERMINAL_STATES,
    SERVICE_REQUEST_TRANSITIONS,
    ServiceRequestState,
    TransitionError,
)
from packages.canonical.storage import SqliteCanonicalStore
from packages.canonical.vocab import ReasonCode

_CANONICAL = Path(__file__).resolve().parents[2] / "packages" / "canonical"
_SCHEMA_PATH = _CANONICAL / "sql" / "schema_v0_1.sql"
_SCHEMA_SQL = _SCHEMA_PATH.read_text(encoding="utf-8")

# The executable DDL only. The file's comments legitimately NAME the constructs
# banned from it (they explain that geometry/GiST live in sql/postgis_postgres.sql
# instead), so scanning the raw text would flag the very documentation that keeps
# the rule honest -- the same treatment test_scheduling_family.py applies.
_SCHEMA_DDL = "\n".join(line.split("--", 1)[0] for line in _SCHEMA_SQL.splitlines()).lower()

_TABLE = "request_state_transitions"

# The write path, as three files. Named explicitly rather than globbed so a new
# module cannot join the write path without someone deciding to add it here.
_WRITE_PATH_MODULES = (
    _CANONICAL / "lifecycle.py",
    _CANONICAL / "storage.py",
    _CANONICAL / "postgres_storage.py",
)

# Tables that existed before this packet. "Additive only" is a promise about what
# was NOT touched, and it is only checkable against a list.
_PRE_EXISTING_TABLES = (
    "tenants", "service_requests", "vehicles", "drivers", "policies", "model_versions",
    "forecast_vintages", "schedule_runs", "decision_alternatives", "decision_events",
    "outcomes", "outbox", "vehicle_observations", "stop_time_observations", "blocks",
    "run_pieces", "deadhead_segments",
)

_LIFECYCLE_METHODS = ("record_transition", "request_lifecycle", "explain_outcome")


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Fixtures: the SAME assertions on both engines wherever the assertion is not
# engine-specific. ADR-0004's mirrored-contract claim is only meaningful if the
# mirrored methods are actually exercised on both sides.
# --------------------------------------------------------------------------- #
@pytest.fixture(params=["sqlite", "postgres"])
def store(request):
    if request.param == "postgres":
        if not pg_is_reachable():
            pytest.skip("PostgreSQL (milexium_dev, port 5432) is not reachable on this machine")
        engine = PostgresCanonicalStore.connect(schema=f"mx_life_{uuid.uuid4().hex}")
        try:
            yield engine
        finally:
            try:
                engine._conn.rollback()
            except Exception:  # pragma: no cover - teardown must not mask a failure
                pass
            engine.drop_schema()
            engine.close()
    else:
        engine = SqliteCanonicalStore()
        try:
            yield engine
        finally:
            engine.close()


@pytest.fixture
def pg():
    """A PostgreSQL store for the engine-specific halves (collation, DDL
    defaults). Skips, never fails, when the instance is absent."""
    if not pg_is_reachable():
        pytest.skip("PostgreSQL (milexium_dev, port 5432) is not reachable on this machine")
    engine = PostgresCanonicalStore.connect(schema=f"mx_life_pg_{uuid.uuid4().hex}")
    try:
        yield engine
    finally:
        try:
            engine._conn.rollback()
        except Exception:  # pragma: no cover
            pass
        engine.drop_schema()
        engine.close()


@pytest.fixture
def tenant(store) -> TenantId:
    tenant_id = new_id(TenantId)
    store.create_tenant(Tenant(tenant_id=tenant_id, name="Synthetic Transit", created_at=_utc(2026, 1, 1)))
    return tenant_id


def _register(engine, tenant_id: TenantId) -> None:
    engine.create_tenant(Tenant(tenant_id=tenant_id, name="Synthetic Transit", created_at=_utc(2026, 1, 1)))


# The packet's own worked example, as a fixture: the 08:00 window had no
# accessible capacity, so at 09:14:03 the request was negotiated to 09:45-10:15,
# and at 09:14:07 that negotiated trip was scheduled.
_REQUESTED_WINDOW = TimeWindow(start=_utc(2026, 7, 1, 8, 0), end=_utc(2026, 7, 1, 8, 30))
_NEGOTIATED_WINDOW = TimeWindow(start=_utc(2026, 7, 1, 9, 45), end=_utc(2026, 7, 1, 10, 15))


def _negotiate(engine, tenant_id: TenantId, request_id: RequestId) -> RequestTransition:
    return engine.record_transition(
        tenant_id=tenant_id,
        request_id=request_id,
        from_state=ServiceRequestState.REQUESTED,
        to_state=ServiceRequestState.NEGOTIATED,
        decided_at=_utc(2026, 7, 1, 9, 14, 3),
        recorded_at=_utc(2026, 7, 1, 9, 14, 3) + timedelta(milliseconds=250),
        actor_type="system",
        actor_id="scheduler",
        reason_codes=(ReasonCode.NO_ACCESSIBLE_CAPACITY,),
        requested_window=_REQUESTED_WINDOW,
        negotiated_window=_NEGOTIATED_WINDOW,
    )


def _schedule(engine, tenant_id: TenantId, request_id: RequestId) -> RequestTransition:
    return engine.record_transition(
        tenant_id=tenant_id,
        request_id=request_id,
        from_state=ServiceRequestState.NEGOTIATED,
        to_state=ServiceRequestState.SCHEDULED,
        decided_at=_utc(2026, 7, 1, 9, 14, 7),
        recorded_at=_utc(2026, 7, 1, 9, 14, 7) + timedelta(milliseconds=10),
        actor_type="system",
        actor_id="scheduler",
    )


def _walk_to(engine, tenant_id: TenantId, request_id: RequestId, target: ServiceRequestState) -> None:
    """Drive one request along the legal path until it is IN `target`.

    Used to put a chain head into each non-initial state so the illegal-target
    grid below can be exercised from every state that a real chain can reach.
    """
    if target is SERVICE_REQUEST_INITIAL_STATE:
        return
    _negotiate(engine, tenant_id, request_id)
    if target is ServiceRequestState.NEGOTIATED:
        return
    if target is ServiceRequestState.DENIED:
        engine.record_transition(
            tenant_id=tenant_id, request_id=request_id,
            from_state=ServiceRequestState.NEGOTIATED, to_state=ServiceRequestState.DENIED,
            decided_at=_utc(2026, 7, 1, 9, 20), recorded_at=_utc(2026, 7, 1, 9, 20, 1),
            actor_type="human", actor_id="dispatcher-token-7",
            reason_codes=(ReasonCode.SHIFT_END,),
        )
        return
    _schedule(engine, tenant_id, request_id)
    if target is ServiceRequestState.SCHEDULED:
        return
    if target in (ServiceRequestState.CANCELLED, ServiceRequestState.NO_SHOW):
        engine.record_transition(
            tenant_id=tenant_id, request_id=request_id,
            from_state=ServiceRequestState.SCHEDULED, to_state=target,
            decided_at=_utc(2026, 7, 1, 10, 0), recorded_at=_utc(2026, 7, 1, 10, 0, 1),
            actor_type="human", actor_id="dispatcher-token-7",
        )
        return
    engine.record_transition(
        tenant_id=tenant_id, request_id=request_id,
        from_state=ServiceRequestState.SCHEDULED, to_state=ServiceRequestState.IN_PROGRESS,
        decided_at=_utc(2026, 7, 1, 9, 46), recorded_at=_utc(2026, 7, 1, 9, 46, 1),
        actor_type="system", actor_id="avl",
    )
    if target is ServiceRequestState.IN_PROGRESS:
        return
    engine.record_transition(
        tenant_id=tenant_id, request_id=request_id,
        from_state=ServiceRequestState.IN_PROGRESS, to_state=ServiceRequestState.COMPLETED,
        decided_at=_utc(2026, 7, 1, 10, 12), recorded_at=_utc(2026, 7, 1, 10, 12, 1),
        actor_type="system", actor_id="avl",
    )


# =========================================================================
# 0. THE STRUCTURAL GUARANTEE: nothing on this path can stamp itself
# =========================================================================


@pytest.mark.parametrize("engine_class", [SqliteCanonicalStore, PostgresCanonicalStore])
@pytest.mark.parametrize("argument", ["decided_at", "recorded_at"])
def test_the_decision_time_is_a_required_argument_with_no_default(engine_class, argument: str) -> None:
    """THE HEADLINE, expressed as a signature rather than as documentation.

    `decided_at` has to come from the caller, at the moment of the decision. A
    default -- ANY default, `None` included, because `None` invites
    `decided_at or now()` two lines later -- would make it possible to write a
    transition without saying when it was decided, and a record that can be
    written that way is a record that will be, on the day someone is retrofitting
    history under time pressure. Asserted for both engines because a signature
    that drifted on one would be exactly the kind of divergence ADR-0004's
    mirrored contract exists to prevent."""
    parameter = inspect.signature(engine_class.record_transition).parameters[argument]

    assert parameter.default is inspect.Parameter.empty, (
        f"{engine_class.__name__}.record_transition({argument}=...) has a default "
        f"({parameter.default!r}); a defaulted decision time is a reconstructed one"
    )
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, (
        f"{argument} must be keyword-only so it can never be supplied by position "
        "and silently swapped with the other clock"
    )


@pytest.mark.parametrize("module_path", _WRITE_PATH_MODULES, ids=lambda p: p.name)
def test_no_module_on_the_write_path_reads_a_clock(module_path: Path) -> None:
    """THE STRUCTURAL HALF OF "at the moment of the decision".

    A signature with no default is only half the guarantee: the store could still
    call `datetime.now()` internally and pass it along. This walks the ACTUAL
    PARSED SOURCE of every module on the write path and asserts that no call to a
    wall-clock function appears anywhere in it.

    Deliberately module-wide rather than scoped to the lifecycle methods. A helper
    that reads a clock is one refactor away from being called from the write path,
    and "no clock in this file at all" is a property a reviewer can check in a
    second, where "no clock reachable from these three methods" is not."""
    forbidden_attributes = {"now", "utcnow", "today", "monotonic", "monotonic_ns", "time_ns"}
    tree = ast.parse(module_path.read_text(encoding="utf-8"))

    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr in forbidden_attributes:
                offenders.append(f"line {node.lineno}: .{func.attr}()")
            if func.attr == "time" and isinstance(func.value, ast.Name) and func.value.id == "time":
                offenders.append(f"line {node.lineno}: time.time()")
        elif isinstance(func, ast.Name) and func.id in forbidden_attributes:
            offenders.append(f"line {node.lineno}: {func.id}()")

    assert not offenders, (
        f"{module_path.name} reads a wall clock at {offenders} -- a lifecycle record "
        "that can stamp itself on write is the 'reconstructed afterwards' artefact "
        "this packet exists to make impossible"
    )


def test_the_decided_at_column_carries_no_sql_default_in_the_ddl() -> None:
    """The schema-level half: the DATABASE cannot stamp a row either.

    A `DEFAULT CURRENT_TIMESTAMP` on `decided_at` would defeat every Python-side
    guarantee above at once, silently, for any writer that reached the table with
    raw SQL. The column definition is read out of the DDL text and asserted bare.

    The `reason_codes` assertion is a POSITIVE CONTROL: that column DOES have a
    default, so this parse is demonstrably capable of finding one. Without it,
    a regex that matched nothing at all would pass this test."""
    block = re.search(
        rf"CREATE TABLE {_TABLE} \((.*?)\n\);", _SCHEMA_SQL, re.DOTALL
    )
    assert block, f"{_TABLE} is not defined in schema_v0_1.sql"
    body = block.group(1)

    decided = [line.strip() for line in body.splitlines() if line.strip().startswith("decided_at")]
    recorded = [line.strip() for line in body.splitlines() if line.strip().startswith("recorded_at")]
    reasons = [line.strip() for line in body.splitlines() if line.strip().startswith("reason_codes")]

    assert len(decided) == 1 and "default" not in decided[0].lower(), (
        f"decided_at carries a SQL DEFAULT: {decided!r}"
    )
    assert len(recorded) == 1 and "default" not in recorded[0].lower(), (
        f"recorded_at carries a SQL DEFAULT: {recorded!r}"
    )
    assert len(reasons) == 1 and "default" in reasons[0].lower(), (
        "positive control failed: reason_codes is supposed to HAVE a default, so a "
        "parse that cannot see it is not evidence about decided_at either"
    )


def test_the_decided_at_column_carries_no_default_in_the_live_database(pg) -> None:
    """The same fact, read back out of the LIVE PostgreSQL catalogue rather than
    out of the file we wrote -- so it is the database's opinion, not ours.

    Paired with the same positive control: `reason_codes` must come back WITH a
    default, or `column_default IS NULL` proves nothing about `decided_at`."""
    defaults = dict(
        pg._conn.execute(
            "SELECT column_name, column_default FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s",
            (pg._schema, _TABLE),
        ).fetchall()
    )

    assert defaults, f"{_TABLE} has no columns in schema {pg._schema}"
    assert defaults["decided_at"] is None, (
        f"the live decided_at column has DEFAULT {defaults['decided_at']!r} -- the "
        "database can stamp a decision time by itself"
    )
    assert defaults["recorded_at"] is None
    assert defaults["reason_codes"] is not None, (
        "positive control failed: reason_codes has a DEFAULT in the DDL, so if this "
        "query reports None for it the query is not seeing defaults at all"
    )


def test_the_two_stores_expose_the_same_lifecycle_contract() -> None:
    """ADR-0004's mirrored contract, for the three new methods: same names, same
    parameters, same defaults. Two near-identical store modules are exactly where
    a signature drifts unnoticed, and a `decided_at` that acquired a default on
    one engine only would be invisible to every test that ran on the other."""
    for name in _LIFECYCLE_METHODS:
        sqlite_signature = inspect.signature(getattr(SqliteCanonicalStore, name))
        postgres_signature = inspect.signature(getattr(PostgresCanonicalStore, name))
        assert sqlite_signature == postgres_signature, (
            f"{name} differs between engines:\n  sqlite:   {sqlite_signature}\n"
            f"  postgres: {postgres_signature}"
        )


def test_the_canonical_package_never_updates_or_deletes_a_lifecycle_row() -> None:
    """APPEND-ONLY, asserted against the source rather than promised in a comment.

    `decision_events` has a deliberate test-only `tamper_with_row` UPDATE helper;
    this table has none, so "append-only" here needs no exception clause and a
    future one would have to be added past this test. A correction to a lifecycle
    record is a further transition, never an edit to a stored one -- if a stored
    row could be rewritten, "created at the moment of the decision" would be
    unfalsifiable."""
    offenders: list[str] = []
    for path in sorted(_CANONICAL.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            lowered = line.lower()
            if _TABLE in lowered and ("update " in lowered or "delete " in lowered):
                offenders.append(f"{path.name}:{number}: {line.strip()}")

    assert not offenders, f"the lifecycle record is written to non-append-only: {offenders}"


# =========================================================================
# 1. RECORDING AND READING BACK -- the packet's own worked example
# =========================================================================


def test_a_negotiation_and_a_schedule_are_recorded_as_an_ordered_history(store, tenant) -> None:
    """THE WORKED EXAMPLE, end to end: request R moved REQUESTED -> NEGOTIATED at
    09:14:03 because the 08:00 window had no accessible capacity, then
    NEGOTIATED -> SCHEDULED at 09:14:07. Both engines."""
    request_id = new_id(RequestId)
    _negotiate(store, tenant, request_id)
    _schedule(store, tenant, request_id)

    history = store.request_lifecycle(tenant, request_id)

    assert [(t.sequence, t.from_state, t.to_state) for t in history] == [
        (1, ServiceRequestState.REQUESTED, ServiceRequestState.NEGOTIATED),
        (2, ServiceRequestState.NEGOTIATED, ServiceRequestState.SCHEDULED),
    ]
    assert history[0].decided_at == _utc(2026, 7, 1, 9, 14, 3)
    assert history[1].decided_at == _utc(2026, 7, 1, 9, 14, 7)
    assert history[0].reason_codes == (ReasonCode.NO_ACCESSIBLE_CAPACITY,)
    assert history[0].actor_type == "system" and history[0].actor_id == "scheduler"
    assert history[0].requested_window == _REQUESTED_WINDOW
    assert history[0].negotiated_window == _NEGOTIATED_WINDOW


def test_the_stored_decision_time_is_the_callers_and_is_not_the_write_time(store, tenant) -> None:
    """THE CLAIM ITSELF, as a round-trip.

    The decision is stated as having happened on 1 July; the row is written down
    a full day later. What comes back must be 1 July -- not the write time, not
    anything derived from it. And the two must come back DISTINCT: a store that
    collapsed them (or that overwrote `decided_at` with `recorded_at`) would still
    pass a test that only checked one field."""
    request_id = new_id(RequestId)
    decided = _utc(2026, 7, 1, 9, 14, 3)
    recorded = _utc(2026, 7, 2, 4, 0, 0)  # a full day later: a late-arriving export

    store.record_transition(
        tenant_id=tenant, request_id=request_id,
        from_state=ServiceRequestState.REQUESTED, to_state=ServiceRequestState.CANCELLED,
        decided_at=decided, recorded_at=recorded,
        actor_type="human", actor_id="rider-token-3",
    )

    (stored,) = store.request_lifecycle(tenant, request_id)
    assert stored.decided_at == decided
    assert stored.recorded_at == recorded
    assert stored.decided_at != stored.recorded_at, (
        "the two clocks collapsed into one -- the whole distinction this record "
        "exists to make is gone"
    )


def test_microsecond_precision_survives_the_round_trip(store, tenant) -> None:
    """Sub-second decision times are not decoration here: an automated scheduler
    makes several decisions inside one second, and a record that truncated them
    would make two distinct decisions indistinguishable in time.

    This is also the case the fixed-width timestamp format exists for -- a
    zero-microsecond value and a non-zero one must both round-trip and must both
    be comparable in SQL (see the collation tests below)."""
    request_id = new_id(RequestId)
    decided = _utc(2026, 7, 1, 9, 14, 3) + timedelta(microseconds=500_001)
    recorded = decided + timedelta(microseconds=1)

    store.record_transition(
        tenant_id=tenant, request_id=request_id,
        from_state=ServiceRequestState.REQUESTED, to_state=ServiceRequestState.CANCELLED,
        decided_at=decided, recorded_at=recorded,
        actor_type="system", actor_id="scheduler",
    )

    (stored,) = store.request_lifecycle(tenant, request_id)
    assert stored.decided_at == decided
    assert stored.recorded_at == recorded
    assert stored.decided_at.microsecond == 500_001


def test_an_unknown_request_has_an_empty_history_rather_than_an_invented_one(store, tenant) -> None:
    """Absence is reported as absence. A store that answered "REQUESTED" for a
    request it has never seen would be fabricating the one thing this record is
    for."""
    assert store.request_lifecycle(tenant, new_id(RequestId)) == ()
    assert store.explain_outcome(tenant, new_id(RequestId)) is None


# =========================================================================
# 2. LEGALITY AT THE RECORD LAYER (not merely at the checker)
# =========================================================================


def test_every_illegal_transition_is_refused_by_the_store_not_just_the_checker(store, tenant) -> None:
    """THE EXHAUSTIVE PROOF, over every state a real chain can be in x every
    illegal target from it -- on both engines, in one store instance.

    The packet's requirement is precisely that the refusal happens at the RECORD
    layer: `check_transition` returning False is worth nothing if the store writes
    the row anyway. So for each of the eight states, a request is driven along the
    legal path until its chain head is in that state, and then every target the
    contract forbids is attempted against the real store. Each attempt must raise
    `TransitionError` AND leave the stored history untouched -- a partial write
    that raised afterwards would be worse than no check at all.

    The four terminal states are included, which is how "nothing can be appended
    after an outcome" gets proved: a terminal state's allowed set is empty, so
    every one of the eight targets is illegal from it."""
    attempted = 0
    for head_state in ServiceRequestState:
        allowed = SERVICE_REQUEST_TRANSITIONS[head_state]
        request_id = new_id(RequestId)
        _walk_to(store, tenant, request_id, head_state)
        before = store.request_lifecycle(tenant, request_id)

        for target in ServiceRequestState:
            if target in allowed:
                continue
            attempted += 1
            with pytest.raises(TransitionError):
                store.record_transition(
                    tenant_id=tenant, request_id=request_id,
                    from_state=head_state, to_state=target,
                    decided_at=_utc(2026, 7, 2, 12, 0), recorded_at=_utc(2026, 7, 2, 12, 0, 1),
                    actor_type="system", actor_id="scheduler",
                    reason_codes=(ReasonCode.SOLVER_TIMEOUT,),
                    requested_window=_REQUESTED_WINDOW,
                    negotiated_window=_NEGOTIATED_WINDOW,
                )
            assert store.request_lifecycle(tenant, request_id) == before, (
                f"the refused transition {head_state.value} -> {target.value} still "
                "changed the stored history"
            )

    # 64 pairs minus the 10 legal ones. Both the derived count and the literal are
    # asserted: the derivation makes this follow the contract table, and the
    # literal makes a table edit that legalised something have to be noticed here
    # rather than quietly shrinking what this test covers.
    legal = sum(len(targets) for targets in SERVICE_REQUEST_TRANSITIONS.values())
    assert attempted == len(ServiceRequestState) ** 2 - legal == 64 - 10 == 54


@pytest.mark.parametrize("terminal", sorted(SERVICE_REQUEST_TERMINAL_STATES, key=lambda s: s.value))
def test_nothing_can_be_appended_after_an_outcome(store, tenant, terminal) -> None:
    """Called out separately from the grid above because of what it means rather
    than what it tests: once a trip has an outcome, that outcome cannot be
    revised in place by appending a "correction" that walks it somewhere else. A
    denial that could later be turned into a completion by a further row would
    make the record worthless as evidence."""
    request_id = new_id(RequestId)
    _walk_to(store, tenant, request_id, terminal)
    length = len(store.request_lifecycle(tenant, request_id))

    for target in ServiceRequestState:
        with pytest.raises(TransitionError):
            store.record_transition(
                tenant_id=tenant, request_id=request_id,
                from_state=terminal, to_state=target,
                decided_at=_utc(2026, 7, 3), recorded_at=_utc(2026, 7, 3),
                actor_type="human", actor_id="dispatcher-token-7",
                reason_codes=(ReasonCode.SHIFT_END,),
                requested_window=_REQUESTED_WINDOW, negotiated_window=_NEGOTIATED_WINDOW,
            )
    assert len(store.request_lifecycle(tenant, request_id)) == length


def test_the_first_transition_must_start_where_the_machine_starts(store, tenant) -> None:
    """A chain that began at SCHEDULED would be a history with its beginning
    missing, and every transition in it could still be individually legal. The
    entry state is DERIVED from the contract table (the one state nothing can
    transition into), so this cannot drift from the machine it is anchored on."""
    for start in ServiceRequestState:
        if start is SERVICE_REQUEST_INITIAL_STATE:
            continue
        target = next(iter(SERVICE_REQUEST_TRANSITIONS[start]), ServiceRequestState.COMPLETED)
        with pytest.raises(LifecycleOrderError):
            store.record_transition(
                tenant_id=tenant, request_id=new_id(RequestId),
                from_state=start, to_state=target,
                decided_at=_utc(2026, 7, 1), recorded_at=_utc(2026, 7, 1),
                actor_type="system", actor_id="scheduler",
                reason_codes=(ReasonCode.SOLVER_TIMEOUT,),
                requested_window=_REQUESTED_WINDOW, negotiated_window=_NEGOTIATED_WINDOW,
            )


def test_a_transition_that_does_not_continue_the_stored_chain_is_refused(store, tenant) -> None:
    """The move is LEGAL in the contract and still wrong here: the request is
    recorded as NEGOTIATED, and this caller thinks it is still REQUESTED.

    That is a lost update or two writers racing, and `LifecycleOrderError` is a
    different type from `TransitionError` because the remedy is different -- re-read
    the chain, do not re-model the state machine."""
    request_id = new_id(RequestId)
    _negotiate(store, tenant, request_id)

    with pytest.raises(LifecycleOrderError):
        store.record_transition(
            tenant_id=tenant, request_id=request_id,
            from_state=ServiceRequestState.REQUESTED,  # stale: it is NEGOTIATED now
            to_state=ServiceRequestState.DENIED,
            decided_at=_utc(2026, 7, 1, 9, 30), recorded_at=_utc(2026, 7, 1, 9, 30),
            actor_type="system", actor_id="scheduler",
            reason_codes=(ReasonCode.SHIFT_END,),
        )
    assert len(store.request_lifecycle(tenant, request_id)) == 1


def test_a_decision_made_before_the_one_it_follows_is_refused(store, tenant) -> None:
    """Decision times along a chain never go backwards. Without this, a
    back-dated row could be appended to make a denial look as though it had been
    decided before the negotiation that caused it -- a rewritten history composed
    entirely of individually-legal rows.

    The positive control matters as much as the refusal: an EQUAL decision time is
    accepted, because an automated scheduler really does reach two conclusions in
    the same microsecond, and a rule that forbade that would push callers into
    fabricating a gap."""
    request_id = new_id(RequestId)
    head = _negotiate(store, tenant, request_id)

    with pytest.raises(LifecycleOrderError):
        store.record_transition(
            tenant_id=tenant, request_id=request_id,
            from_state=ServiceRequestState.NEGOTIATED, to_state=ServiceRequestState.SCHEDULED,
            decided_at=head.decided_at - timedelta(microseconds=1),
            recorded_at=_utc(2026, 7, 2),
            actor_type="system", actor_id="scheduler",
        )

    same_instant = store.record_transition(
        tenant_id=tenant, request_id=request_id,
        from_state=ServiceRequestState.NEGOTIATED, to_state=ServiceRequestState.SCHEDULED,
        decided_at=head.decided_at, recorded_at=_utc(2026, 7, 2),
        actor_type="system", actor_id="scheduler",
    )
    assert same_instant.sequence == 2


def test_an_illegal_pair_cannot_be_constructed_as_a_record_at_all(store, tenant) -> None:
    """The SECOND net, independent of any store: a `RequestTransition` object
    holding an illegal pair cannot be built anywhere -- a test fixture, a future
    importer, an evidence-pack reader. Without this, "the history contains no
    illegal path" would hold only for histories that went through a store."""
    with pytest.raises(ValidationError, match="illegal transition"):
        RequestTransition(
            transition_id=new_id(RequestTransitionId),
            tenant_id=new_id(TenantId),
            request_id=new_id(RequestId),
            sequence=1,
            from_state=ServiceRequestState.COMPLETED,
            to_state=ServiceRequestState.REQUESTED,
            decided_at=_utc(2026, 7, 1),
            recorded_at=_utc(2026, 7, 1),
            actor_type="system",
            actor_id="scheduler",
        )


def test_a_row_forced_in_by_raw_sql_cannot_be_read_back_as_a_record(store, tenant) -> None:
    """THE READ LAYER IS A NET TOO, and this is the case that proves the database
    CHECKs are not the whole story.

    `from_state`/`to_state` have CHECK constraints, but they constrain the
    VOCABULARY, not the transition table -- `completed -> requested` is two valid
    words and an impossible move, so raw SQL puts the row in happily. What must
    not happen is that it then reads back as a valid `RequestTransition` and gets
    shown to someone as history. It raises on read instead.

    Expressing this as a portable statement across both engines is deliberate: the
    parameter style differs, nothing else does."""
    request_id = new_id(RequestId)
    placeholder = "?" if isinstance(store, SqliteCanonicalStore) else "%s"
    columns = (
        "transition_id, tenant_id, request_id, sequence, from_state, to_state, "
        "decided_at, recorded_at, actor_type, actor_id"
    )
    values = (
        str(new_id(RequestTransitionId)), str(tenant), str(request_id), 1,
        ServiceRequestState.COMPLETED.value, ServiceRequestState.REQUESTED.value,
        iso_fixed_utc(_utc(2026, 7, 1)), iso_fixed_utc(_utc(2026, 7, 1)),
        "system", "scheduler",
    )
    marks = ",".join([placeholder] * len(values))
    store._conn.execute(
        f"INSERT INTO {_TABLE} ({columns}) VALUES ({marks})", values  # noqa: S608
    )
    store._conn.commit()

    with pytest.raises(ValidationError, match="illegal transition"):
        store.request_lifecycle(tenant, request_id)


# =========================================================================
# 3. THE BACKDATED WRITE -- refused in Python AND by the database
# =========================================================================


def test_a_write_recorded_before_it_was_decided_is_refused(store, tenant) -> None:
    """`recorded_at` before `decided_at` means the row claims to have been written
    down before the decision it records. That is either a clock defect or a
    fabricated history; either way the record stops being evidence of
    decision-time capture, which is why it gets its own error type.

    The positive control is the boundary: EQUAL timestamps are accepted, because a
    system that writes the instant it decides is the ideal case, not an error."""
    request_id = new_id(RequestId)
    decided = _utc(2026, 7, 1, 9, 14, 3)

    with pytest.raises(BackdatedRecordError):
        store.record_transition(
            tenant_id=tenant, request_id=request_id,
            from_state=ServiceRequestState.REQUESTED, to_state=ServiceRequestState.CANCELLED,
            decided_at=decided, recorded_at=decided - timedelta(microseconds=1),
            actor_type="system", actor_id="scheduler",
        )
    assert store.request_lifecycle(tenant, request_id) == ()

    accepted = store.record_transition(
        tenant_id=tenant, request_id=request_id,
        from_state=ServiceRequestState.REQUESTED, to_state=ServiceRequestState.CANCELLED,
        decided_at=decided, recorded_at=decided,
        actor_type="system", actor_id="scheduler",
    )
    assert accepted.decided_at == accepted.recorded_at


def test_the_database_itself_refuses_a_backdated_row(store, tenant) -> None:
    """The Python refusal above is application code, and application code can be
    refactored away. The CHECK constraint cannot be, and this reaches PAST the
    store with raw SQL to prove the database is the one saying no.

    The positive control -- the same statement with the two timestamps the right
    way round -- is what stops this passing because of an unrelated constraint
    violation such as a bad column list."""
    request_id = new_id(RequestId)
    placeholder = "?" if isinstance(store, SqliteCanonicalStore) else "%s"
    columns = (
        "transition_id, tenant_id, request_id, sequence, from_state, to_state, "
        "decided_at, recorded_at, actor_type, actor_id"
    )
    marks = ",".join([placeholder] * 10)
    statement = f"INSERT INTO {_TABLE} ({columns}) VALUES ({marks})"  # noqa: S608

    def row(decided: datetime, recorded: datetime, sequence: int) -> tuple:
        return (
            str(new_id(RequestTransitionId)), str(tenant), str(request_id), sequence,
            "requested", "cancelled", iso_fixed_utc(decided), iso_fixed_utc(recorded),
            "system", "scheduler",
        )

    decided = _utc(2026, 7, 1, 9, 14, 3)
    with pytest.raises(Exception) as raised:
        store._conn.execute(statement, row(decided, decided - timedelta(microseconds=1), 1))
        store._conn.commit()
    assert "check" in type(raised.value).__name__.lower() or "constraint" in str(raised.value).lower(), (
        f"the insert failed with {raised.value!r}, which does not look like the CHECK "
        "constraint refusing it -- this test may be passing for an unrelated reason"
    )
    try:
        store._conn.rollback()
    except Exception:  # pragma: no cover - sqlite autocommits per execute here
        pass

    # POSITIVE CONTROL: the same statement, the timestamps the right way round.
    store._conn.execute(statement, row(decided, decided + timedelta(microseconds=1), 1))
    store._conn.commit()
    assert len(store.request_lifecycle(tenant, request_id)) == 1


@pytest.mark.parametrize(
    "decided_offset,recorded_offset",
    [
        # THE CASE THAT ACTUALLY BREAKS, and the one an earlier version of this
        # test missed: a whole-second decision time written down a quarter of a
        # second later. Under `datetime.isoformat()` that is '...03+00:00' next to
        # '...03.250000+00:00', and those two compare the WRONG WAY under this
        # server's collation -- so the CHECK constraint would REJECT this entirely
        # ordinary row. It is also the most common shape in practice, because an
        # operator export states decision times to the second.
        (0, 250_000),
        (0, 1),
        (0, 999_999),
        # A pair that BOTH carry fractions -- which the naive format happens to
        # survive. Kept so the parameter set covers the passing shape too, and
        # labelled here so nobody mistakes it for the case under defence.
        (500_000, 750_000),
        # And the ideal case: written the instant it was decided.
        (250_000, 250_000),
    ],
)
def test_the_check_constraint_accepts_ordinary_rows_across_the_fractional_second_boundary(
    store, tenant, decided_offset: int, recorded_offset: int
) -> None:
    """THE CASE A NAIVE IMPLEMENTATION GETS WRONG, and the reason this table
    writes fixed-width timestamps while the rest of the repository does not.

    Each row here is legitimate -- `recorded_at` is at or after `decided_at` -- so
    each must be ACCEPTED by the database. Rendered the repository's usual way
    (`datetime.isoformat()`, which elides a zero fraction) the first three
    parameters compare non-chronologically under PostgreSQL's collation and the
    CHECK constraint would refuse them.

    A NOTE ON HOW THIS TEST WAS BUILT, because it is the point. Its first version
    only used the (500000, 750000) pair, and a mutation that reverted
    `iso_fixed_utc` to `.isoformat()` left it GREEN -- two values that both carry
    fractions compare correctly even under the bad collation, so the test was
    asserting the one shape the defect does not touch. The whole-second cases are
    what make it bite."""
    base = _utc(2026, 7, 1, 9, 14, 3)
    request_id = new_id(RequestId)

    stored = store.record_transition(
        tenant_id=tenant, request_id=request_id,
        from_state=ServiceRequestState.REQUESTED, to_state=ServiceRequestState.CANCELLED,
        decided_at=base + timedelta(microseconds=decided_offset),
        recorded_at=base + timedelta(microseconds=recorded_offset),
        actor_type="system", actor_id="scheduler",
    )

    assert stored.sequence == 1
    (read_back,) = store.request_lifecycle(tenant, request_id)
    assert read_back.decided_at == base + timedelta(microseconds=decided_offset)
    assert read_back.recorded_at == base + timedelta(microseconds=recorded_offset)


def test_a_genuinely_backdated_row_is_refused_across_the_same_boundary(store, tenant) -> None:
    """The other direction of the same trap: a row whose `recorded_at` is a whole
    second earlier than a sub-second `decided_at` really IS backdated, and the
    naive rendering would have the database happily accept it."""
    base = _utc(2026, 7, 1, 9, 14, 3)

    with pytest.raises(BackdatedRecordError):
        store.record_transition(
            tenant_id=tenant, request_id=new_id(RequestId),
            from_state=ServiceRequestState.REQUESTED, to_state=ServiceRequestState.CANCELLED,
            decided_at=base + timedelta(microseconds=500_000),
            recorded_at=base,  # whole second: EARLIER, and the naive format says otherwise
            actor_type="system", actor_id="scheduler",
        )


def test_the_collation_would_break_a_naive_timestamp_format(pg) -> None:
    """THE FINDING, demonstrated on the live server rather than argued.

    This asserts that the repository's everyday `datetime.isoformat()` rendering
    compares WRONG under this PostgreSQL instance's collation, and that the
    fixed-width rendering compares right for the identical pair of instants. It is
    what makes `iso_fixed_utc` a load-bearing decision rather than a style choice,
    and it is the reason the CHECK constraint in schema_v0_1.sql can be trusted.

    If this test ever fails, it does NOT mean the code is broken -- it means the
    server's collation changed and the trap no longer bites here. The fixed-width
    assertion below is the one that must always hold; the naive assertion is
    documentation of why, and its failure is a signal to re-derive the reasoning
    on the new collation rather than to delete the format."""
    earlier = _utc(2026, 7, 1, 9, 14, 3)
    later = earlier + timedelta(microseconds=500_000)

    (collation,) = pg._conn.execute(
        "SELECT datcollate FROM pg_database WHERE datname = current_database()"
    ).fetchone()

    (naive,) = pg._conn.execute(
        "SELECT %s::text >= %s::text", (later.isoformat(), earlier.isoformat())
    ).fetchone()
    (fixed,) = pg._conn.execute(
        "SELECT %s::text >= %s::text", (iso_fixed_utc(later), iso_fixed_utc(earlier))
    ).fetchone()

    assert fixed is True, (
        f"fixed-width timestamps do not compare chronologically under collation "
        f"{collation!r} -- the recorded_at >= decided_at CHECK is unsound on this server"
    )
    assert naive is False, (
        f"under collation {collation!r} the naive isoformat rendering now compares "
        "correctly, so the trap this format defends against does not bite here. Do "
        "NOT delete the fixed-width format on the strength of this -- re-derive the "
        "argument for the collation actually in use"
    )


# =========================================================================
# 4. REASON CODES: a denial or a negotiation must say why
# =========================================================================


def test_a_denial_with_no_reason_code_cannot_be_recorded(store, tenant) -> None:
    """"Denied, reason unrecorded" is the single outcome this whole packet exists
    to make impossible. A denial is the moment a rider does not get a trip they
    are legally entitled to, and a record of it without grounds is worse than no
    record: it looks like evidence and answers nothing."""
    request_id = new_id(RequestId)
    with pytest.raises(ValidationError, match="reason code"):
        store.record_transition(
            tenant_id=tenant, request_id=request_id,
            from_state=ServiceRequestState.REQUESTED, to_state=ServiceRequestState.DENIED,
            decided_at=_utc(2026, 7, 1), recorded_at=_utc(2026, 7, 1),
            actor_type="human", actor_id="dispatcher-token-7",
        )
    assert store.request_lifecycle(tenant, request_id) == ()


def test_a_negotiation_must_state_why_and_carry_both_windows(store, tenant) -> None:
    """A negotiation is "you asked for X, we offer Y, because Z". All three parts
    are mandatory, and each omission is refused separately:

      * no reason code -> the rider is told their window moved and not why;
      * no negotiated window -> "we negotiated" with nothing to point at;
      * no REQUESTED window -> the delta a rider actually experienced becomes
        uncomputable FOREVER, because nothing else in the schema records what was
        originally asked for at the moment the offer was made."""
    request_id = new_id(RequestId)
    common = dict(
        tenant_id=tenant, request_id=request_id,
        from_state=ServiceRequestState.REQUESTED, to_state=ServiceRequestState.NEGOTIATED,
        decided_at=_utc(2026, 7, 1), recorded_at=_utc(2026, 7, 1),
        actor_type="system", actor_id="scheduler",
    )

    with pytest.raises(ValidationError, match="reason code"):
        store.record_transition(
            **common, requested_window=_REQUESTED_WINDOW, negotiated_window=_NEGOTIATED_WINDOW
        )
    with pytest.raises(ValidationError, match="window"):
        store.record_transition(
            **common, reason_codes=(ReasonCode.PICKUP_WINDOW,),
            requested_window=_REQUESTED_WINDOW,
        )
    with pytest.raises(ValidationError, match="window"):
        store.record_transition(
            **common, reason_codes=(ReasonCode.PICKUP_WINDOW,),
            negotiated_window=_NEGOTIATED_WINDOW,
        )
    assert store.request_lifecycle(tenant, request_id) == ()


def test_a_transition_that_is_neither_may_carry_no_reason_codes(store, tenant) -> None:
    """The complement, and it has to be tested or the rules above would be
    satisfied by simply demanding reason codes everywhere -- which would push
    callers into citing a code for a completion, diluting the vocabulary until
    a cited code stops meaning anything."""
    request_id = new_id(RequestId)
    transition = store.record_transition(
        tenant_id=tenant, request_id=request_id,
        from_state=ServiceRequestState.REQUESTED, to_state=ServiceRequestState.CANCELLED,
        decided_at=_utc(2026, 7, 1), recorded_at=_utc(2026, 7, 1),
        actor_type="human", actor_id="rider-token-3",
    )
    assert transition.reason_codes == ()


def test_free_text_cannot_reach_the_record_in_place_of_a_reason_code(store, tenant) -> None:
    """Reason codes are a closed vocabulary, never generated prose (blueprint 06).
    Two doors are shut here: an unrecognised code string, and an extra field --
    an ingest that carried the dispatcher's own words as `note` would otherwise
    have them read back out of an evidence pack as if they were structured
    grounds."""
    with pytest.raises(ValidationError):
        store.record_transition(
            tenant_id=tenant, request_id=new_id(RequestId),
            from_state=ServiceRequestState.REQUESTED, to_state=ServiceRequestState.DENIED,
            decided_at=_utc(2026, 7, 1), recorded_at=_utc(2026, 7, 1),
            actor_type="human", actor_id="dispatcher-token-7",
            reason_codes=("no vehicle was available that morning",),  # type: ignore[arg-type]
        )
    with pytest.raises(ValidationError):
        RequestTransition(
            transition_id=new_id(RequestTransitionId), tenant_id=new_id(TenantId),
            request_id=new_id(RequestId), sequence=1,
            from_state=ServiceRequestState.REQUESTED, to_state=ServiceRequestState.CANCELLED,
            decided_at=_utc(2026, 7, 1), recorded_at=_utc(2026, 7, 1),
            actor_type="human", actor_id="rider-token-3",
            note="the rider phoned to say they no longer needed it",  # type: ignore[call-arg]
        )


def test_an_unrecognised_actor_type_is_refused(store, tenant) -> None:
    """The actor vocabulary is deliberately the one `decision_events` already
    uses. A third value here would mean "who decided" no longer means the same
    thing in the lifecycle record as in the decision ledger, and an evidence pack
    drawing on both would be silently comparing two vocabularies."""
    with pytest.raises(ValidationError):
        store.record_transition(
            tenant_id=tenant, request_id=new_id(RequestId),
            from_state=ServiceRequestState.REQUESTED, to_state=ServiceRequestState.CANCELLED,
            decided_at=_utc(2026, 7, 1), recorded_at=_utc(2026, 7, 1),
            actor_type="robot", actor_id="scheduler",
        )
    with pytest.raises(ValidationError):
        store.record_transition(
            tenant_id=tenant, request_id=new_id(RequestId),
            from_state=ServiceRequestState.REQUESTED, to_state=ServiceRequestState.CANCELLED,
            decided_at=_utc(2026, 7, 1), recorded_at=_utc(2026, 7, 1),
            actor_type="system", actor_id="",  # nobody is not an actor
        )


def test_a_reversed_time_window_is_refused(store, tenant) -> None:
    """A window whose start is after its end yields a NEGATIVE width, which would
    subtract from any aggregate built over these deltas -- the same class of
    defect the scheduling family rejects for pull-out/pull-in. Equal bounds are
    accepted: a zero-width window is degenerate but real (a fixed appointment
    time)."""
    with pytest.raises(ValidationError):
        TimeWindow(start=_utc(2026, 7, 1, 9, 0), end=_utc(2026, 7, 1, 8, 0))
    assert TimeWindow(start=_utc(2026, 7, 1, 9, 0), end=_utc(2026, 7, 1, 9, 0)).minutes == 0.0


# =========================================================================
# 5. "EXPLAIN THIS OUTCOME"
# =========================================================================


def test_explain_names_the_outcome_the_grounds_and_the_window_delta(store, tenant) -> None:
    """THE VIEW THE SENTENCE PROMISES, on a request that was negotiated 105
    minutes away from what the rider asked for and then denied at the end of a
    shift.

    Three answers, all from stored rows and none reconstructed: what happened
    (DENIED), on what grounds (SHIFT_END for the outcome itself, and
    NO_ACCESSIBLE_CAPACITY earlier in the chain, which is why it was negotiated at
    all), and how far the offered trip sat from the requested one (+105 minutes at
    both edges)."""
    request_id = new_id(RequestId)
    _negotiate(store, tenant, request_id)
    store.record_transition(
        tenant_id=tenant, request_id=request_id,
        from_state=ServiceRequestState.NEGOTIATED, to_state=ServiceRequestState.DENIED,
        decided_at=_utc(2026, 7, 1, 9, 20), recorded_at=_utc(2026, 7, 1, 9, 20, 1),
        actor_type="human", actor_id="dispatcher-token-7",
        reason_codes=(ReasonCode.SHIFT_END,),
    )

    explanation = store.explain_outcome(tenant, request_id)

    assert explanation is not None
    assert explanation.is_terminal is True
    assert explanation.terminal_state is ServiceRequestState.DENIED
    assert explanation.current_state is ServiceRequestState.DENIED
    assert explanation.decided_at == _utc(2026, 7, 1, 9, 20)
    assert explanation.outcome_reason_codes == (ReasonCode.SHIFT_END,)
    assert explanation.all_reason_codes == (
        ReasonCode.NO_ACCESSIBLE_CAPACITY,
        ReasonCode.SHIFT_END,
    )
    assert explanation.window_start_delta_minutes == 105.0
    assert explanation.window_end_delta_minutes == 105.0
    assert explanation.requested_window == _REQUESTED_WINDOW
    assert explanation.negotiated_window == _NEGOTIATED_WINDOW
    assert [t.sequence for t in explanation.transitions] == [1, 2]


def test_an_in_flight_request_is_reported_as_having_no_outcome_yet(store, tenant) -> None:
    """A request still in flight has no terminal state, and the view says so with
    `None` rather than reporting its current state as though it were the outcome.
    Getting this wrong would be the most damaging kind of wrong: a scheduled trip
    described as a completed one.

    THE SHARP EDGE, pinned here rather than left to a reader's assumption:
    `outcome_reason_codes` is the codes on the MOST RECENT transition, so on an
    in-flight request it is populated with the grounds for the latest decision and
    does NOT explain an outcome (there is none). It has to be read together with
    `is_terminal`. This test asserts that behaviour explicitly so nobody builds a
    "reasons for denial" report off the field alone."""
    request_id = new_id(RequestId)
    _negotiate(store, tenant, request_id)

    mid_flight = store.explain_outcome(tenant, request_id)
    assert mid_flight is not None
    assert mid_flight.is_terminal is False
    assert mid_flight.terminal_state is None
    assert mid_flight.current_state is ServiceRequestState.NEGOTIATED
    assert mid_flight.outcome_reason_codes == (ReasonCode.NO_ACCESSIBLE_CAPACITY,), (
        "outcome_reason_codes carries the latest decision's grounds even when there "
        "is no outcome -- that is the documented behaviour, and it is why the field "
        "must be read alongside is_terminal"
    )

    _schedule(store, tenant, request_id)
    explanation = store.explain_outcome(tenant, request_id)

    assert explanation is not None
    assert explanation.is_terminal is False
    assert explanation.terminal_state is None
    assert explanation.current_state is ServiceRequestState.SCHEDULED
    assert explanation.outcome_reason_codes == ()


def test_the_window_delta_is_absent_rather_than_zero_when_nothing_was_negotiated(store, tenant) -> None:
    """A request cancelled straight from REQUESTED never had a window moved. The
    delta must be None, NOT 0.0 -- zero would positively assert that the offer
    matched the request, which is a different and false statement, and it is the
    one that would survive into a summary table unnoticed."""
    request_id = new_id(RequestId)
    store.record_transition(
        tenant_id=tenant, request_id=request_id,
        from_state=ServiceRequestState.REQUESTED, to_state=ServiceRequestState.CANCELLED,
        decided_at=_utc(2026, 7, 1, 8, 5), recorded_at=_utc(2026, 7, 1, 8, 5),
        actor_type="human", actor_id="rider-token-3",
    )

    explanation = store.explain_outcome(tenant, request_id)

    assert explanation is not None
    assert explanation.window_start_delta_minutes is None
    assert explanation.window_end_delta_minutes is None
    assert explanation.requested_window is None and explanation.negotiated_window is None
    assert explanation.terminal_state is ServiceRequestState.CANCELLED
    assert explanation.outcome_reason_codes == ()


def test_a_completed_trip_explains_itself_with_no_reason_codes(store, tenant) -> None:
    """The happy path is part of the claim too -- "booked" is one of the five
    outcomes the sentence names. A trip that ran carries the negotiation delta it
    was actually served under and no grounds on the completion itself, because
    there is nothing to justify."""
    request_id = new_id(RequestId)
    _walk_to(store, tenant, request_id, ServiceRequestState.COMPLETED)

    explanation = store.explain_outcome(tenant, request_id)

    assert explanation is not None
    assert explanation.terminal_state is ServiceRequestState.COMPLETED
    assert explanation.outcome_reason_codes == ()
    assert explanation.all_reason_codes == (ReasonCode.NO_ACCESSIBLE_CAPACITY,)
    assert explanation.window_start_delta_minutes == 105.0
    assert [t.to_state for t in explanation.transitions] == [
        ServiceRequestState.NEGOTIATED,
        ServiceRequestState.SCHEDULED,
        ServiceRequestState.IN_PROGRESS,
        ServiceRequestState.COMPLETED,
    ]


def test_the_two_engines_explain_an_identical_history_identically() -> None:
    """ADR-0004's mirrored contract where it is most visible: the same history,
    written to both engines, must produce the SAME explanation object.

    Not merely the same fields -- the same value, compared whole. A per-engine
    difference in ordering, in reason-code de-duplication, or in how a window is
    reconstructed would show up here and nowhere else, and it would mean the view
    a regulator was shown depended on which database happened to serve it."""
    if not pg_is_reachable():
        pytest.skip("PostgreSQL (milexium_dev, port 5432) is not reachable on this machine")

    tenant_id, request_id = new_id(TenantId), new_id(RequestId)
    sqlite_store = SqliteCanonicalStore()
    postgres_store = PostgresCanonicalStore.connect(schema=f"mx_life_cmp_{uuid.uuid4().hex}")
    try:
        for engine in (sqlite_store, postgres_store):
            _register(engine, tenant_id)
            _walk_to(engine, tenant_id, request_id, ServiceRequestState.COMPLETED)

        from_sqlite = sqlite_store.explain_outcome(tenant_id, request_id)
        from_postgres = postgres_store.explain_outcome(tenant_id, request_id)

        assert from_sqlite is not None and from_postgres is not None
        # transition_id is minted per write, so it legitimately differs; everything
        # a reader is shown must not.
        comparable = {"transitions"}
        assert from_sqlite.model_dump(exclude=comparable) == from_postgres.model_dump(
            exclude=comparable
        )
        assert [
            t.model_dump(exclude={"transition_id"}) for t in from_sqlite.transitions
        ] == [t.model_dump(exclude={"transition_id"}) for t in from_postgres.transitions]
    finally:
        sqlite_store.close()
        postgres_store.drop_schema()
        postgres_store.close()


# =========================================================================
# 6. TENANT SCOPING AT THE STORE LEVEL (the policy is test_lifecycle_rls.py)
# =========================================================================


def test_one_operators_lifecycle_record_is_invisible_to_another(store, tenant) -> None:
    """Two operators, the SAME `request_id` -- which is what happens when two
    agencies both import from a source system that numbers requests from 1.

    Each reads only its own chain. The positive control (each tenant CAN see its
    own) is what stops this passing on an empty table."""
    other = new_id(TenantId)
    _register(store, other)
    request_id = new_id(RequestId)

    _negotiate(store, tenant, request_id)
    store.record_transition(
        tenant_id=other, request_id=request_id,
        from_state=ServiceRequestState.REQUESTED, to_state=ServiceRequestState.DENIED,
        decided_at=_utc(2026, 7, 1, 7, 0), recorded_at=_utc(2026, 7, 1, 7, 0),
        actor_type="human", actor_id="dispatcher-token-9",
        reason_codes=(ReasonCode.MAX_RIDE_TIME,),
    )

    mine = store.request_lifecycle(tenant, request_id)
    theirs = store.request_lifecycle(other, request_id)

    assert [t.to_state for t in mine] == [ServiceRequestState.NEGOTIATED]
    assert [t.to_state for t in theirs] == [ServiceRequestState.DENIED]
    assert store.explain_outcome(tenant, request_id).terminal_state is None
    assert store.explain_outcome(other, request_id).terminal_state is ServiceRequestState.DENIED


def test_chain_positions_are_per_tenant_and_start_at_one(store, tenant) -> None:
    """The chain position is derived from what the ACTING tenant can see, so two
    operators sharing a `request_id` each get their own 1, 2, 3...

    Worth pinning: a globally-derived sequence would collide on the UNIQUE
    constraint under RLS on PostgreSQL (where the other tenant's rows are simply
    invisible to the MAX), and would leak the other operator's activity through
    the gaps in one's own numbering."""
    other = new_id(TenantId)
    _register(store, other)
    request_id = new_id(RequestId)

    _negotiate(store, tenant, request_id)
    first_for_other = store.record_transition(
        tenant_id=other, request_id=request_id,
        from_state=ServiceRequestState.REQUESTED, to_state=ServiceRequestState.CANCELLED,
        decided_at=_utc(2026, 7, 1, 7, 0), recorded_at=_utc(2026, 7, 1, 7, 0),
        actor_type="human", actor_id="rider-token-9",
    )
    second_for_tenant = _schedule(store, tenant, request_id)

    assert first_for_other.sequence == 1
    assert second_for_tenant.sequence == 2


# =========================================================================
# 7. PORTABILITY AND VOCABULARY (ADR-0002)
# =========================================================================


def test_schema_v0_1_still_executes_unmodified_on_a_bare_sqlite_connection() -> None:
    """The portability contract, run against the file's ACTUAL BYTES on a plain
    `sqlite3` connection with no store class involved -- so a Postgres-only
    construct cannot have arrived with the new table. Row-level security for it is
    Postgres-only and lives in rls_postgres.sql, applied separately; that
    separation is what keeps this file executable here."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(_SCHEMA_SQL)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()

    assert _TABLE in tables
    missing = [t for t in _PRE_EXISTING_TABLES if t not in tables]
    assert not missing, f"pre-existing tables disappeared from the portable schema: {missing}"


@pytest.mark.parametrize(
    "construct",
    ["jsonb", "serial", "geometry", "timestamptz", "generated always", "gist", "on conflict"],
)
def test_the_portable_schema_contains_no_postgres_only_construct(construct: str) -> None:
    """A regression guard naming the constructs that would break the SQLite
    execution above, so a future edit fails with a readable reason rather than an
    opaque OperationalError."""
    assert construct not in _SCHEMA_DDL, (
        f"schema_v0_1.sql contains the Postgres-only construct {construct!r}"
    )


def test_the_sql_state_vocabulary_matches_the_python_enum_in_both_directions() -> None:
    """Two declarations of one vocabulary can drift, and the failure is silent in
    the worse direction: a state Python accepts but the CHECK rejects fails
    loudly, while a state the CHECK accepts and Python does not would let raw SQL
    write a row that can never be read back as an entity.

    Pinned for BOTH new columns, because they are two separate CHECK clauses and
    a change applied to one is exactly what gets missed."""
    block = re.search(rf"CREATE TABLE {_TABLE} \((.*?)\n\);", _SCHEMA_SQL, re.DOTALL)
    assert block
    body = block.group(1)
    python_states = {state.value for state in ServiceRequestState}

    for column in ("from_state", "to_state"):
        clause = re.search(rf"{column}\s+TEXT NOT NULL CHECK \({column} IN\s*\((.*?)\)\)", body, re.DOTALL)
        assert clause, f"{column} has no CHECK ... IN (...) clause"
        sql_states = set(re.findall(r"'([a-z_]+)'", clause.group(1)))
        assert sql_states == python_states, (
            f"{column}'s SQL vocabulary {sorted(sql_states)} has drifted from "
            f"ServiceRequestState {sorted(python_states)}"
        )


def test_the_stored_reason_codes_are_canonical_json(store, tenant) -> None:
    """Reason codes are stored as a JSON array of the enum's own values, the same
    encoding `decision_events.reason_codes` uses. Asserted against the raw stored
    bytes rather than the round-trip, because a round-trip through one class's own
    encoder and decoder would agree with itself whatever it wrote."""
    request_id = new_id(RequestId)
    _negotiate(store, tenant, request_id)

    placeholder = "?" if isinstance(store, SqliteCanonicalStore) else "%s"
    (raw,) = store._conn.execute(
        f"SELECT reason_codes FROM {_TABLE} WHERE tenant_id = {placeholder} "  # noqa: S608
        f"AND request_id = {placeholder}",
        (str(tenant), str(request_id)),
    ).fetchone()

    assert json.loads(raw) == ["NO_ACCESSIBLE_CAPACITY"]
