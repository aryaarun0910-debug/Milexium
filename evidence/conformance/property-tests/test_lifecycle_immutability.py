"""Adversarial conformance: the lifecycle record is IMMUTABLE and its transaction
time is the DATABASE'S, not the caller's. MX-A-LIFECYCLE-IMMUTABILITY-012.

WHAT THIS FILE EXISTS TO CLOSE. An external audit of this repository made two P0
findings against `request_state_transitions` -- the table presented as the answer
to "what happened to this trip, who decided, and when?":

  1. `recorded_at` was a CALLER argument. The only rule was
     `recorded_at >= decided_at`, and both sides came from the same caller, so a
     transition asserting a 2020-01-01 decision "recorded" one second later was
     accepted. The system proved that two assertions were ordered and nothing at
     all about when the row entered Milexium.
  2. The table was called append-only because no application code issued UPDATE
     or DELETE against it. The auditor wrote a valid denial, issued a direct SQL
     UPDATE changing `actor_id`, committed it, and read the forged actor back
     through the normal lifecycle API with no violation reported. A coding
     convention is not a database invariant.

Both probes are re-run here, verbatim, as regression tests. They are the first
two tests a reader should look at.

WHY THE ACTING CREDENTIAL IS THE WHOLE POINT. ADR-0046 found that the container's
bootstrap credential holds `rolsuper` and `rolbypassrls`, and that PostgreSQL
checks both BEFORE ownership and before FORCE -- so a test that runs privileged
proves nothing about what a deployment can do. Worse, a table's OWNER can
`DROP TRIGGER`, `ALTER TABLE ... DISABLE TRIGGER` and `CREATE OR REPLACE` the
function a trigger calls, so an immutability trigger installed by the credential
it is meant to constrain is the same convention wearing a database's clothes.

Every Postgres test below therefore runs as a real deployment credential --
`milexium_dev` on the native PostgreSQL 17 (ADR-0006) and `milexium_app` on the
container (ADR-0052) -- and asserts, BEFORE drawing any conclusion, that the
acting role: is not a superuser, does not hold BYPASSRLS, does NOT own the
lifecycle table, and cannot `SET ROLE` to the role that does.

FOUR WAYS THIS SUITE COULD PASS WHILE PROVING NOTHING, each closed by a test
rather than argued away:

  * *The write never happened.* Every refusal is paired with a read-back proving
    the original row is still there, unchanged, with its actor intact.
  * *The refusal came from somewhere else.* PostgreSQL refusals are asserted on
    SQLSTATE -- 42501 for the privilege boundary, MX001 for the trigger, MX002
    for the transaction-time bound -- never on message text.
  * *The guard is removable by the credential it constrains.* Separate tests
    prove this connection cannot drop the triggers, cannot disable them, cannot
    grant itself UPDATE, and cannot take ownership.
  * *The trigger is never actually exercised* on the sealed path, because the
    privilege check fires first. It is exercised explicitly against a deliberately
    UNSEALED schema, where the acting role does hold UPDATE -- so both layers are
    demonstrated independently rather than one hiding the other.

ONE TEST HERE ASSERTS A WEAKNESS RATHER THAN A GUARANTEE, and it is not an
oversight: `test_the_credential_CAN_still_destroy_the_table_and_this_is_the_residual_risk`
demonstrates that this credential can `DROP TABLE`, because PostgreSQL permits
that to the SCHEMA owner and the application owns the disposable schema. It is
written down as a test so the residual cannot quietly disappear from anyone's
mental model of what "immutable" covers here.

SYNTHETIC FIXTURES ONLY. Status: **Demonstrated**. There is no consented operator
data in this repository and nothing here is Validated. What is demonstrated is
the mechanism, on two engines and two real credentials -- not that any agency's
history is protected, because no agency's history is here.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.canonical.entities import Tenant
from app.canonical.ids import RequestId, RequestTransitionId, TenantId, new_id
from app.canonical.lifecycle import (
    LIFECYCLE_LATE_ARRIVAL_THRESHOLD_SECONDS,
    RECORDED_AT_TOLERANCE_SECONDS,
    LateRecordingReason,
    LifecycleChainError,
    UndeclaredLateRecordError,
    iso_fixed_utc,
    lifecycle_transition_hash,
    transition_payload,
)
from app.canonical.lifecycle_verify import verify_lifecycle_chain
from app.canonical.state_machine import ServiceRequestState
from app.canonical.storage import SqliteCanonicalStore
from app.canonical.transaction_clock import transaction_time
from app.canonical.vocab import ReasonCode

psycopg = pytest.importorskip("psycopg")

from app.canonical.observation_store import (  # noqa: E402
    _application_credential,
    _read_compose_env,
)
from app.canonical.postgres_storage import (  # noqa: E402
    LIFECYCLE_OWNER_SEPARATED,
    PostgresCanonicalStore,
    is_reachable as pg_is_reachable,
)

_TABLE = "request_state_transitions"
_LEDGER_OWNER = "milexium_ledger_owner"

#: PostgreSQL SQLSTATEs this suite asserts on. Asserting a class of error rather
#: than a message is what stops a test passing because some unrelated failure
#: happened to contain the right words -- and stops it failing when a message is
#: reworded.
_INSUFFICIENT_PRIVILEGE = "42501"
_APPEND_ONLY_VIOLATION = "MX001"
_TRANSACTION_TIME_VIOLATION = "MX002"

_BACKFILL = LateRecordingReason.BATCH_IMPORT


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Fixtures. The Postgres parameter is the DEPLOYMENT CREDENTIAL on each instance
# that exists on this machine -- never a superuser, never the owner.
# --------------------------------------------------------------------------- #


def _container_credential() -> tuple[str, str, str] | None:
    env = _read_compose_env()
    user, password = _application_credential(env)
    if not password:
        return None
    return env.get("POSTGRES_DB", "milexium_dev"), user, password


def _container_reachable() -> bool:
    credential = _container_credential()
    if credential is None:
        return False
    dbname, user, password = credential
    return pg_is_reachable(port=5433, dbname=dbname, user=user, password=password)


@pytest.fixture(params=["native-milexium_dev", "container-milexium_app"])
def pg(request):
    """A sealed `PostgresCanonicalStore` on each reachable instance.

    TWO INSTANCES, TWO CREDENTIALS, ON PURPOSE. The native PostgreSQL 17 is where
    `PostgresCanonicalStore` normally runs, as `milexium_dev`. The container is
    where ADR-0052's `milexium_app` lives, and `milexium_app` is the credential the
    packet requires this to be proved under -- the one an actual deployment would
    hold. Running the identical battery against both is also what would catch a
    guarantee that only holds on the machine it was written on.
    """
    if request.param == "native-milexium_dev":
        if not pg_is_reachable():
            pytest.skip("native PostgreSQL (milexium_dev, 5432) is not reachable")
        store = PostgresCanonicalStore.connect(schema=f"mx_imm_{uuid.uuid4().hex}")
    else:
        if not _container_reachable():
            pytest.skip("containerized PostgreSQL (milexium_app, 5433) is not reachable")
        dbname, user, password = _container_credential()
        store = PostgresCanonicalStore.connect(
            host="localhost", port=5433, dbname=dbname, user=user, password=password,
            schema=f"mx_imm_{uuid.uuid4().hex}",
        )
    try:
        yield store
    finally:
        try:
            store._conn.rollback()
        except Exception:  # pragma: no cover - teardown must not mask a failure
            pass
        store.drop_schema()
        store.close()


@pytest.fixture
def unsealed_pg():
    """A store whose lifecycle table was DELIBERATELY left owned by the acting
    role, so the trigger can be exercised on its own.

    On the sealed path the privilege boundary refuses an UPDATE before the trigger
    is ever reached, so a test there cannot tell a working trigger from an absent
    one. This fixture is the only place `_leave_lifecycle_unsealed` is used, and
    the tests that use it say explicitly that they are measuring the WEAKER
    configuration.
    """
    if not pg_is_reachable():
        pytest.skip("native PostgreSQL (milexium_dev, 5432) is not reachable")
    store = PostgresCanonicalStore.connect(
        schema=f"mx_unsealed_{uuid.uuid4().hex}", _leave_lifecycle_unsealed=True
    )
    try:
        yield store
    finally:
        try:
            store._conn.rollback()
        except Exception:  # pragma: no cover
            pass
        store.drop_schema()
        store.close()


@pytest.fixture
def sqlite_store():
    store = SqliteCanonicalStore()
    try:
        yield store
    finally:
        store.close()


def _tenant(store) -> TenantId:
    tenant_id = new_id(TenantId)
    store.create_tenant(
        Tenant(tenant_id=tenant_id, name="Synthetic Transit", created_at=_utc(2026, 1, 1))
    )
    return tenant_id


def _record_denial(store, tenant_id: TenantId) -> RequestId:
    """The row every mutation test tries to forge: a denial with a stated ground.

    A denial is the sharpest case on purpose. It is the moment a rider did not get
    a trip they may be legally entitled to, and `actor_id` is who refused them --
    the exact field the audit rewrote.
    """
    request_id = new_id(RequestId)
    store.record_transition(
        tenant_id=tenant_id,
        request_id=request_id,
        from_state=ServiceRequestState.REQUESTED,
        to_state=ServiceRequestState.DENIED,
        decided_at=_utc(2026, 7, 1, 9, 14, 3),
        actor_type="human",
        actor_id="dispatcher-token-7",
        reason_codes=(ReasonCode.NO_ACCESSIBLE_CAPACITY,),
        late_reason=_BACKFILL,
    )
    return request_id


def _actor(store, tenant_id: TenantId, request_id: RequestId) -> str:
    (transition,) = store.request_lifecycle(tenant_id, request_id)
    return transition.actor_id


def _sqlstate(error: Exception) -> str | None:
    return getattr(error, "sqlstate", None)


def _assert_bound_by_the_database(store) -> None:
    """Assert the acting role is genuinely constrained -- INLINE, before the test
    that calls it draws any conclusion.

    `test_the_acting_credential_is_unprivileged` asserts the same thing as a
    standalone test, which is this repository's usual pattern. It is repeated
    inline in the tests that matter most because a standalone precondition test
    can be skipped, deselected, or reordered, and every refusal in this file is
    meaningless if the connection could have bypassed the guard anyway: PostgreSQL
    checks `rolsuper` and `rolbypassrls` BEFORE ownership and before FORCE
    (ADR-0046). Three cheap assertions are worth more than the argument that they
    are checked elsewhere.
    """
    acting, is_super, bypasses = store._conn.execute(
        "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
    ).fetchone()
    assert is_super is False, f"acting as superuser {acting!r} -- this result is vacuous"
    assert bypasses is False, f"acting role {acting!r} holds BYPASSRLS -- this result is vacuous"
    (can_assume,) = store._conn.execute(
        "SELECT pg_has_role(current_user, %s, 'USAGE')", (_LEDGER_OWNER,)
    ).fetchone()
    assert can_assume is False, (
        f"{acting!r} can SET ROLE to {_LEDGER_OWNER!r} -- it can become the owner of "
        "the table it is supposedly constrained on, so nothing below is a boundary"
    )


# =========================================================================
# 0. THE AUDIT'S OWN PROBES, RE-RUN
# =========================================================================


def test_the_audits_backdated_insert_is_now_refused_by_the_database(pg) -> None:
    """THE FIRST P0, VERBATIM. The auditor inserted a transition whose
    `decided_at` was 2020-01-01 and whose `recorded_at` was one second later, and
    it was accepted -- proving only that two caller assertions were ordered.

    The same statement now fails at the DATABASE, with the transaction-time
    SQLSTATE, on a connection holding no more privilege than a deployment does.
    Note which guard catches it: NOT the column DEFAULT. A DEFAULT fires only when
    the column is omitted, and this insert supplies it -- which is exactly why the
    repair is a bounding trigger and not merely a default.

    The positive control is essential here and is not decoration: the identical
    statement with a CURRENT transaction time must be ACCEPTED, or this test would
    pass just as happily against a table that rejects every insert.
    """
    _assert_bound_by_the_database(pg)
    tenant_id = _tenant(pg)
    pg._use_tenant(tenant_id)

    with pytest.raises(psycopg.Error) as raised:
        _raw_insert_pg(
            pg,
            tenant_id,
            decided_at=_utc(2020, 1, 1),
            recorded_at=_utc(2020, 1, 1, 0, 0, 1),
            late_recording_reason=_BACKFILL,
        )
    assert _sqlstate(raised.value) == _TRANSACTION_TIME_VIOLATION, (
        f"the backdated insert failed with SQLSTATE {_sqlstate(raised.value)!r} "
        f"rather than {_TRANSACTION_TIME_VIOLATION} -- something other than the "
        "transaction-time bound refused it, so this is not evidence that the bound "
        "works"
    )
    pg._conn.rollback()

    # POSITIVE CONTROL: the same shape, honestly stamped.
    pg._use_tenant(tenant_id)
    request_id = _raw_insert_pg(
        pg, tenant_id, decided_at=_utc(2020, 1, 1), late_recording_reason=_BACKFILL
    )
    assert len(pg.request_lifecycle(tenant_id, request_id)) == 1, (
        "positive control failed: a raw insert with a truthful transaction time was "
        "also refused, so the rejection above proves nothing about backdating"
    )


def test_the_audits_forged_actor_update_is_now_refused(pg) -> None:
    """THE SECOND P0, VERBATIM. The auditor wrote a valid denial, issued a direct
    SQL `UPDATE` changing `actor_id`, committed it, and read the forged actor back
    through the normal lifecycle API with no violation reported.

    The same UPDATE now fails, and the stored actor is unchanged. The SQLSTATE is
    asserted to be one of the two guards this packet installed -- the privilege
    boundary (the sealed deployment path, where the acting role holds no UPDATE at
    all) or the append-only trigger -- and NOT, say, a syntax error or a
    tenant-policy denial that would have hidden a missing guard.
    """
    _assert_bound_by_the_database(pg)
    tenant_id = _tenant(pg)
    request_id = _record_denial(pg, tenant_id)
    assert _actor(pg, tenant_id, request_id) == "dispatcher-token-7"

    pg._use_tenant(tenant_id)
    with pytest.raises(psycopg.Error) as raised:
        pg._conn.execute(
            f"UPDATE {_TABLE} SET actor_id = %s WHERE request_id = %s",  # noqa: S608
            ("forged-actor", str(request_id)),
        )
        pg._conn.commit()
    assert _sqlstate(raised.value) in {_INSUFFICIENT_PRIVILEGE, _APPEND_ONLY_VIOLATION}, (
        f"the forging UPDATE failed with SQLSTATE {_sqlstate(raised.value)!r}, which "
        "is neither the privilege boundary nor the append-only trigger -- it was "
        "refused by something this packet did not install"
    )
    pg._conn.rollback()

    assert _actor(pg, tenant_id, request_id) == "dispatcher-token-7", (
        "the stored actor changed -- the audit's forgery still works"
    )
    assert pg.verify_request_lifecycle(tenant_id, request_id).ok


def _raw_insert_pg(store, tenant_id: TenantId, **overrides) -> RequestId:
    """One syntactically valid transition, written by RAW SQL, past every Python
    guard. `recorded_at` defaults to the current instant so a test can vary
    exactly one thing at a time."""
    request_id = overrides.pop("request_id", new_id(RequestId))
    decided_at = overrides.pop("decided_at", transaction_time() - timedelta(seconds=1))
    recorded_at = overrides.pop("recorded_at", transaction_time())
    late = overrides.pop("late_recording_reason", None)
    from_state = overrides.pop("from_state", ServiceRequestState.REQUESTED)
    to_state = overrides.pop("to_state", ServiceRequestState.DENIED)
    sequence = overrides.pop("sequence", 1)
    transition_id = overrides.pop("transition_id", new_id(RequestTransitionId))
    actor_id = overrides.pop("actor_id", "dispatcher-token-7")
    prev_hash = overrides.pop("prev_hash", None)
    lag = overrides.pop(
        "ingest_lag_seconds", (recorded_at - decided_at).total_seconds()
    )
    reason_codes = (ReasonCode.NO_ACCESSIBLE_CAPACITY,)
    payload = transition_payload(
        transition_id=transition_id, tenant_id=tenant_id, request_id=request_id,
        from_state=from_state, to_state=to_state, decided_at=decided_at,
        recorded_at=recorded_at, actor_type="human", actor_id=actor_id,
        reason_codes=reason_codes, requested_window=None, negotiated_window=None,
        late_recording_reason=late,
    )
    row_hash = overrides.pop(
        "hash",
        lifecycle_transition_hash(
            prev_hash=prev_hash, payload=payload, sequence=sequence, request_id=request_id
        ),
    )
    assert not overrides, f"unused overrides {sorted(overrides)}"
    store._conn.execute(
        f"INSERT INTO {_TABLE} (transition_id, tenant_id, request_id, sequence, "  # noqa: S608
        "from_state, to_state, decided_at, recorded_at, actor_type, actor_id, "
        "reason_codes, ingest_lag_seconds, late_recording_reason, prev_hash, hash) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            str(transition_id), str(tenant_id), str(request_id), sequence,
            from_state.value, to_state.value, iso_fixed_utc(decided_at),
            iso_fixed_utc(recorded_at), "human", actor_id,
            '["NO_ACCESSIBLE_CAPACITY"]', lag,
            None if late is None else late.value, prev_hash, row_hash,
        ),
    )
    store._conn.commit()
    return request_id


# =========================================================================
# 1. THE PRECONDITIONS EVERY POSTGRES RESULT ABOVE AND BELOW RESTS ON
# =========================================================================


def test_the_acting_credential_is_unprivileged(pg) -> None:
    """ADR-0046's rule, applied before anything else is believed: PostgreSQL
    checks `rolsuper` and `rolbypassrls` BEFORE ownership and before FORCE, so a
    privileged connection would sail through every guard in this file and every
    test would pass while enforcing nothing.

    This is the assertion that makes the rest of the file evidence rather than
    theatre, and it is why the container store connects as `milexium_app` (ADR-0052)
    rather than as the image's bootstrap `POSTGRES_USER`, which holds both bits.
    """
    acting, is_super, bypasses = pg._conn.execute(
        "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
    ).fetchone()

    assert is_super is False, f"acting as superuser {acting!r} -- every result here is vacuous"
    assert bypasses is False, f"acting role {acting!r} holds BYPASSRLS"


def test_the_lifecycle_table_is_owned_by_a_role_this_credential_cannot_become(pg) -> None:
    """THE STRUCTURAL HEART OF THE REPAIR, and the reason a trigger alone was not
    enough.

    A table's owner can `DROP TRIGGER`, `ALTER TABLE ... DISABLE TRIGGER` and
    `CREATE OR REPLACE` the function the trigger calls. So an immutability trigger
    installed BY the application credential is removable BY the application
    credential -- ADR-0063's own "a guard living only in the application is a guard
    a future direct-SQL path walks around", one layer down.

    Three facts together are the boundary, and any one of them alone would be a
    false comfort:
      * the table is owned by `milexium_ledger_owner`;
      * this connection is NOT that role;
      * this connection cannot `SET ROLE` to it -- membership runs one way only,
        so the ledger owner can act as the application and never the reverse.
    """
    assert pg.lifecycle_immutability == LIFECYCLE_OWNER_SEPARATED, (
        f"this store reports {pg.lifecycle_immutability!r}: the cluster bootstrap "
        "(platform/infra/compose/initdb/02-lifecycle-ledger-bootstrap.sql) has not been run "
        "here, so the table is still owned by the credential the guard is meant to "
        "constrain and nothing below is a boundary"
    )

    owner, acting = pg._conn.execute(
        "SELECT pg_get_userbyid(c.relowner), current_user FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %s AND c.relname = %s",
        (pg._schema, _TABLE),
    ).fetchone()

    assert owner == _LEDGER_OWNER, f"{_TABLE} is owned by {owner!r}, not the ledger owner"
    assert owner != acting, (
        f"the acting credential {acting!r} OWNS the lifecycle table, so every guard "
        "on it is one statement away from being removed"
    )

    (can_assume,) = pg._conn.execute(
        "SELECT pg_has_role(current_user, %s, 'USAGE')", (_LEDGER_OWNER,)
    ).fetchone()
    assert can_assume is False, (
        f"{acting!r} can SET ROLE to {_LEDGER_OWNER!r} -- the ownership separation "
        "is cosmetic, because this connection can simply become the owner"
    )


def test_the_credential_holds_insert_and_select_and_nothing_else(pg) -> None:
    """The privilege matrix, read out of the catalogue rather than assumed from
    the file that set it.

    Exactly INSERT and SELECT. Not UPDATE, not DELETE, not TRUNCATE, not
    REFERENCES, not TRIGGER -- TRIGGER in particular, because a role that may
    create triggers on this table could create one that rewrites `NEW` on the way
    in.
    """
    granted = {
        row[0]
        for row in pg._conn.execute(
            "SELECT privilege_type FROM information_schema.table_privileges "
            "WHERE table_schema = %s AND table_name = %s AND grantee = current_user",
            (pg._schema, _TABLE),
        ).fetchall()
    }

    assert granted == {"INSERT", "SELECT"}, (
        f"the deployment credential holds {sorted(granted)} on {_TABLE}. A "
        "correction to this record is a new transition; nothing about it is an "
        "UPDATE, a DELETE or a TRUNCATE, so holding those privileges is holding the "
        "ability to rewrite history for no operational reason"
    )


def test_the_guards_are_installed_and_owned_by_the_ledger_owner(pg) -> None:
    """The four triggers exist, and the functions they call belong to the ledger
    owner rather than to this connection.

    The ownership of the FUNCTION is the part that is easy to miss: a trigger this
    connection cannot drop, calling a function it CAN `CREATE OR REPLACE`, is a
    guard with a public switch on the back.
    """
    rows = pg._conn.execute(
        "SELECT t.tgname, pg_get_userbyid(p.proowner) "
        "FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "JOIN pg_proc p ON p.oid = t.tgfoid "
        "WHERE n.nspname = %s AND c.relname = %s AND NOT t.tgisinternal "
        "ORDER BY t.tgname",
        (pg._schema, _TABLE),
    ).fetchall()

    names = [name for name, _ in rows]
    assert names == [
        "milexium_lifecycle_bound_recorded_at",
        "milexium_lifecycle_reject_delete",
        "milexium_lifecycle_reject_truncate",
        "milexium_lifecycle_reject_update",
    ], f"the installed triggers are {names!r}"

    for name, function_owner in rows:
        assert function_owner == _LEDGER_OWNER, (
            f"trigger {name} calls a function owned by {function_owner!r} -- this "
            "connection can replace that function's body with a no-op"
        )


# =========================================================================
# 2. THE CREDENTIAL CANNOT REMOVE THE GUARD
# =========================================================================


@pytest.mark.parametrize(
    "statement",
    [
        "DROP TRIGGER milexium_lifecycle_reject_update ON {table}",
        "ALTER TABLE {table} DISABLE TRIGGER milexium_lifecycle_reject_update",
        "ALTER TABLE {table} DISABLE TRIGGER ALL",
        "ALTER TABLE {table} OWNER TO CURRENT_USER",
        "CREATE OR REPLACE FUNCTION public.milexium_reject_lifecycle_mutation() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$",
    ],
    ids=[
        "drop-the-trigger", "disable-the-trigger", "disable-all-triggers",
        "take-ownership", "replace-the-guard-function",
    ],
)
def test_the_credential_cannot_disarm_the_guard(pg, statement: str) -> None:
    """FIVE WAYS A DETERMINED HOLDER OF THIS CREDENTIAL WOULD TRY TO GET ITS
    UPDATE BACK, all refused on privilege.

    This is the test that separates a boundary from a convention. Proving that
    UPDATE is refused is worth very little if the same connection can drop the
    thing refusing it in the statement before -- and that was precisely the state
    the audit found, one level up: append-only enforced by nobody writing an
    UPDATE.

    Each statement is asserted to fail on privilege, and the guards are asserted
    still present AND ENABLED afterwards, so a statement that "failed" by silently
    doing nothing would still be caught.
    """
    _assert_bound_by_the_database(pg)
    pg._conn.rollback()
    with pytest.raises(psycopg.Error) as raised:
        pg._conn.execute(statement.format(table=_TABLE))
        pg._conn.commit()
    assert _sqlstate(raised.value) == _INSUFFICIENT_PRIVILEGE, (
        f"{statement!r} failed with SQLSTATE {_sqlstate(raised.value)!r} rather than "
        "a privilege error -- it may have failed for a reason that will not hold"
    )
    pg._conn.rollback()

    (surviving,) = pg._conn.execute(
        "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %s AND c.relname = %s AND NOT t.tgisinternal AND t.tgenabled <> 'D'",
        (pg._schema, _TABLE),
    ).fetchone()
    assert surviving == 4, f"only {surviving} enabled guards remain after {statement!r}"


def test_granting_itself_update_is_a_warning_that_grants_nothing(pg) -> None:
    """A CASE THAT DOES NOT RAISE, AND WOULD HAVE BEEN A FALSE GREEN IF TESTED
    THAT WAY.

    `GRANT UPDATE ON ... TO CURRENT_USER` from a role holding no grant option is
    NOT an error in PostgreSQL: it emits a warning ("no privileges were granted")
    and returns success. A test written as `pytest.raises(...)` here fails -- and
    the tempting reading of that failure is "the credential CAN grant itself
    UPDATE", which is wrong. The right assertion is about the resulting privilege
    set, not about an exception.

    So: run the GRANT, let it succeed, and check the catalogue. Nothing was
    granted, and the UPDATE that follows is still refused.
    """
    tenant_id = _tenant(pg)
    request_id = _record_denial(pg, tenant_id)

    pg._conn.execute(f"GRANT UPDATE ON {_TABLE} TO CURRENT_USER")  # noqa: S608
    pg._conn.commit()

    granted = {
        row[0]
        for row in pg._conn.execute(
            "SELECT privilege_type FROM information_schema.table_privileges "
            "WHERE table_schema = %s AND table_name = %s AND grantee = current_user",
            (pg._schema, _TABLE),
        ).fetchall()
    }
    assert granted == {"INSERT", "SELECT"}, (
        f"the GRANT actually took effect: the credential now holds {sorted(granted)}"
    )

    pg._use_tenant(tenant_id)
    with pytest.raises(psycopg.Error) as raised:
        pg._conn.execute(f"UPDATE {_TABLE} SET actor_id = 'forged-actor'")  # noqa: S608
        pg._conn.commit()
    assert _sqlstate(raised.value) in {_INSUFFICIENT_PRIVILEGE, _APPEND_ONLY_VIOLATION}
    pg._conn.rollback()
    assert _actor(pg, tenant_id, request_id) == "dispatcher-token-7"


def test_the_credential_CAN_still_destroy_the_table_and_this_is_the_residual_risk(
    pg,
) -> None:
    """A TEST THAT ASSERTS A WEAKNESS, on purpose, because the alternative is a
    claim that is broader than the enforcement.

    `DROP TABLE` in PostgreSQL is permitted to the table's owner OR to the owner
    of the SCHEMA containing it. The lifecycle table is owned by
    `milexium_ledger_owner`, but the disposable schema is created by -- and
    therefore owned by -- the application credential, so that credential can drop
    the table outright. `DROP SCHEMA ... CASCADE` is the same hole with a wider
    blast radius, and this store's own teardown depends on it.

    WHAT THIS DOES AND DOES NOT MEAN. The credential cannot alter one field of one
    row: it cannot change who denied a rider, or on what grounds, or when. It CAN
    delete the whole table, loudly and unmistakably. Those are different threats --
    a silent single-field edit is undetectable and survives review; a missing table
    is the first thing anyone notices -- but "immutable" must not be said without
    this sentence attached.

    THE FIX, stated so it is not mistaken for unknown: in a real deployment the
    schema must be owned by a migration role rather than by the application, and
    the application granted USAGE only. That is Specified and NOT implemented; the
    per-run disposable schema this test harness depends on is what stands in the
    way here.
    """
    tenant_id = _tenant(pg)
    _record_denial(pg, tenant_id)

    (owns_schema,) = pg._conn.execute(
        "SELECT pg_get_userbyid(nspowner) = current_user FROM pg_namespace WHERE nspname = %s",
        (pg._schema,),
    ).fetchone()
    assert owns_schema is True, (
        "the acting credential no longer owns the schema -- if that is deliberate, "
        "this residual has been closed and this test should become an assertion "
        "that the DROP is refused"
    )

    pg._conn.execute(f"DROP TABLE {_TABLE}")  # noqa: S608
    pg._conn.commit()

    (still_there,) = pg._conn.execute(
        "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %s AND c.relname = %s",
        (pg._schema, _TABLE),
    ).fetchone()
    assert still_there == 0, (
        "the DROP was refused after all -- good news, and this test now overstates "
        "the residual risk; rewrite it as a refusal test"
    )


# =========================================================================
# 3. MUTATION IS REFUSED -- ON THE DEPLOYMENT PATH AND BY THE TRIGGER ITSELF
# =========================================================================


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE {table} SET actor_id = 'forged-actor'",
        "UPDATE {table} SET reason_codes = '[]'",
        "UPDATE {table} SET decided_at = '2020-01-01T00:00:00.000000+00:00'",
        "DELETE FROM {table}",
        "TRUNCATE {table}",
    ],
    ids=["forge-the-actor", "erase-the-grounds", "backdate-the-decision",
         "delete-the-denial", "truncate-the-history"],
)
def test_every_mutation_of_a_recorded_denial_is_refused(pg, statement: str) -> None:
    """The five shapes a rewritten history actually takes, each refused, each
    followed by a read-back proving the denial is intact.

    They are not interchangeable. Forging the actor changes WHO refused a rider;
    erasing the reason codes turns a refusal with stated grounds into "denied,
    reason unrecorded" -- the outcome this whole record family exists to make
    impossible; backdating the decision breaks the tie between the record and when
    it was made; the two removals destroy the evidence outright.
    """
    _assert_bound_by_the_database(pg)
    tenant_id = _tenant(pg)
    request_id = _record_denial(pg, tenant_id)

    pg._use_tenant(tenant_id)
    with pytest.raises(psycopg.Error) as raised:
        pg._conn.execute(statement.format(table=_TABLE))
        pg._conn.commit()
    assert _sqlstate(raised.value) in {_INSUFFICIENT_PRIVILEGE, _APPEND_ONLY_VIOLATION}
    pg._conn.rollback()

    (stored,) = pg.request_lifecycle(tenant_id, request_id)
    assert stored.actor_id == "dispatcher-token-7"
    assert stored.reason_codes == (ReasonCode.NO_ACCESSIBLE_CAPACITY,)
    assert stored.decided_at == _utc(2026, 7, 1, 9, 14, 3)
    assert pg.verify_request_lifecycle(tenant_id, request_id).ok


@pytest.mark.parametrize(
    "statement",
    ["UPDATE {table} SET actor_id = 'forged-actor'", "DELETE FROM {table}", "TRUNCATE {table}"],
    ids=["update", "delete", "truncate"],
)
def test_the_trigger_itself_refuses_mutation_where_privilege_would_not(
    unsealed_pg, statement: str
) -> None:
    """THE SECOND LAYER, MEASURED ON ITS OWN.

    On the sealed deployment path the privilege check fires first, so those tests
    cannot distinguish a working trigger from a missing one. Here the acting role
    still owns the table and therefore holds UPDATE, DELETE and TRUNCATE outright
    -- and the statement is refused anyway, with the append-only SQLSTATE.

    This configuration is deliberately the WEAKER one: the acting role could drop
    this trigger (that is exactly what `test_the_credential_cannot_disarm_the_guard`
    proves it cannot do on the sealed path). What is being measured is only that
    the trigger works, not that it is unremovable.
    """
    tenant_id = _tenant(unsealed_pg)
    request_id = _record_denial(unsealed_pg, tenant_id)

    unsealed_pg._use_tenant(tenant_id)
    with pytest.raises(psycopg.Error) as raised:
        unsealed_pg._conn.execute(statement.format(table=_TABLE))
        unsealed_pg._conn.commit()
    assert _sqlstate(raised.value) == _APPEND_ONLY_VIOLATION, (
        f"expected the append-only trigger ({_APPEND_ONLY_VIOLATION}); got "
        f"{_sqlstate(raised.value)!r}. On an unsealed schema the acting role holds "
        "the privilege, so anything else means the trigger is not what refused this"
    )
    unsealed_pg._conn.rollback()

    (stored,) = unsealed_pg.request_lifecycle(tenant_id, request_id)
    assert stored.actor_id == "dispatcher-token-7"


def test_an_unsealed_schema_is_reported_as_the_weaker_configuration(unsealed_pg) -> None:
    """The store must SAY which of the two it got. A single boolean "immutable"
    would let the fallback -- a trigger the acting role can drop -- be reported as
    the same thing as the sealed ledger, and that conflation is how a repository
    ends up claiming a boundary it does not have."""
    assert unsealed_pg.lifecycle_immutability == "trigger_only"

    owner, acting = unsealed_pg._conn.execute(
        "SELECT pg_get_userbyid(c.relowner), current_user FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %s AND c.relname = %s",
        (unsealed_pg._schema, _TABLE),
    ).fetchone()
    assert owner == acting, (
        "the unsealed fixture is not actually unsealed, so the trigger tests using "
        "it are measuring the sealed path and proving nothing about the trigger"
    )


@pytest.mark.parametrize(
    "statement",
    [
        f"UPDATE {_TABLE} SET actor_id = 'forged-actor'",
        f"DELETE FROM {_TABLE} WHERE 1 = 1",
        # The unqualified form specifically: SQLite's truncate optimization skips
        # per-row machinery for `DELETE FROM t`, and it is disabled only because
        # this table carries a DELETE trigger. Asserting the qualified case alone
        # would leave the shape a cleanup script actually writes untested.
        f"DELETE FROM {_TABLE}",
    ],
    ids=["update", "qualified-delete", "unqualified-delete"],
)
def test_sqlite_refuses_mutation_too(sqlite_store, statement: str) -> None:
    """The demo engine gets the same triggers, and they work -- with a materially
    weaker claim attached, stated here rather than in a footnote.

    SQLite has no roles and no privileges. Any process that can open the file can
    drop these triggers. So this proves the application cannot mutate the record by
    accident; it does NOT prove a boundary against anyone holding the file, and
    SQLite must never be cited as evidence for the credential separation that
    `test_the_lifecycle_table_is_owned_by_a_role_this_credential_cannot_become`
    proves on PostgreSQL.
    """
    tenant_id = _tenant(sqlite_store)
    request_id = _record_denial(sqlite_store, tenant_id)

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        sqlite_store._conn.execute(statement)
        sqlite_store._conn.commit()

    (stored,) = sqlite_store.request_lifecycle(tenant_id, request_id)
    assert stored.actor_id == "dispatcher-token-7"
    assert sqlite_store.verify_request_lifecycle(tenant_id, request_id).ok


# =========================================================================
# 4. TRANSACTION TIME IS THE DATABASE'S
# =========================================================================


def test_the_transaction_clock_is_the_only_clock_the_write_path_reads(pg) -> None:
    """One line in the package can make every stamped time wrong, and this asserts
    it is exactly one line.

    `test_lifecycle_record.py` asserts by AST that lifecycle.py, storage.py and
    postgres_storage.py contain NO wall-clock call at all -- which is what protects
    `decided_at` from ever being defaulted. That assertion can only stay that
    strong if the writer's clock lives somewhere else, so this pins the other half:
    `transaction_clock.py` is that somewhere, and it does nothing but read the
    clock.
    """
    from pathlib import Path

    module = Path(__file__).resolve().parents[3] / "app" / "canonical" / "transaction_clock.py"
    source = module.read_text(encoding="utf-8")

    assert "datetime.now(timezone.utc)" in source
    assert "def transaction_time()" in source
    # No second entry point, and nothing that takes a caller-supplied instant: a
    # `transaction_time(at=...)` would hand the caller back the very capability
    # this packet removed.
    definitions = [line for line in source.splitlines() if line.startswith("def ")]
    assert definitions == ["def transaction_time() -> datetime:"], (
        f"transaction_clock.py defines {definitions!r} -- it must expose exactly "
        "one, argument-free, or a caller can once again choose the transaction time"
    )


def test_an_omitted_transaction_time_is_stamped_by_the_server(pg) -> None:
    """THE TRUSTED DEFAULT. A raw INSERT that names no `recorded_at` at all is
    stamped by the database's own clock rather than failing on NOT NULL.

    This is the "the database stamps it" half of the repair. It is NOT the half
    that closed the audit finding -- a DEFAULT fires only when the column is
    omitted, and the audit supplied it -- but it means a writer that forgets the
    column cannot produce a row with no transaction time, and it puts the server's
    clock in the path by default rather than by convention.
    """
    tenant_id = _tenant(pg)
    request_id = new_id(RequestId)
    pg._use_tenant(tenant_id)

    before = transaction_time()
    pg._conn.execute(
        f"INSERT INTO {_TABLE} (transition_id, tenant_id, request_id, sequence, "  # noqa: S608
        "from_state, to_state, decided_at, actor_type, actor_id, reason_codes, "
        "ingest_lag_seconds, hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            str(new_id(RequestTransitionId)), str(tenant_id), str(request_id), 1,
            "requested", "cancelled", iso_fixed_utc(before - timedelta(seconds=2)),
            "system", "scheduler", "[]", 2.0, "0" * 64,
        ),
    )
    pg._conn.commit()
    after = transaction_time()

    (stamped,) = pg._conn.execute(
        f"SELECT recorded_at FROM {_TABLE} WHERE request_id = %s",  # noqa: S608
        (str(request_id),),
    ).fetchone()
    stamped_at = datetime.fromisoformat(stamped)

    # THE WINDOW IS WIDENED BY THE TOLERANCE, and that is the finding rather than
    # a fudge: this comparison spans TWO clocks -- the test process's and the
    # database server's -- and against the container they are measurably not the
    # same one. The first version of this assertion was a bare
    # `before <= stamped <= after` and it failed on the container by 836
    # microseconds. That is exactly the skew `RECORDED_AT_TOLERANCE_SECONDS`
    # exists to absorb, and a test that demanded perfect agreement between two
    # hosts' clocks would be asserting something the system does not claim.
    #
    # It stays sharp: the row's `decided_at` is two seconds earlier and the
    # tolerance is 60, so a DEFAULT that copied another column, or that was a
    # constant, or that never fired at all, still fails here.
    tolerance = timedelta(seconds=RECORDED_AT_TOLERANCE_SECONDS)
    assert before - tolerance <= stamped_at <= after + tolerance, (
        f"the server stamped {stamped!r}, further than the clock tolerance from the "
        "window this insert happened in -- the DEFAULT is not the server clock"
    )
    assert abs((stamped_at - before).total_seconds()) < 1.0, (
        f"the server stamp {stamped!r} is more than a second from this write, which "
        "is far more skew than two clocks on one machine should show -- something "
        "other than clock_timestamp() produced it"
    )


@pytest.mark.parametrize(
    "offset_seconds",
    [-3600 * 24 * 365, -300, -61, 61, 3600],
    ids=["a-year-ago", "five-minutes-ago", "just-past-the-bound",
         "just-into-the-future", "an-hour-ahead"],
)
def test_a_transaction_time_far_from_the_server_clock_is_refused(pg, offset_seconds: int) -> None:
    """THE BOUND, in both directions and at its edges.

    Backwards is the audit's forgery: a row claiming to have entered the system
    long ago. Forwards is the mirror: a row claiming to have been written at a
    time nobody can yet check. `-61` and `+61` are one second past the bound, so
    this fails if the tolerance is quietly widened -- a test using only "a year
    ago" would still pass against a bound of a month.
    """
    tenant_id = _tenant(pg)
    pg._use_tenant(tenant_id)

    with pytest.raises(psycopg.Error) as raised:
        _raw_insert_pg(
            pg,
            tenant_id,
            decided_at=transaction_time() - timedelta(days=400),
            recorded_at=transaction_time() + timedelta(seconds=offset_seconds),
            late_recording_reason=_BACKFILL,
        )
    assert _sqlstate(raised.value) == _TRANSACTION_TIME_VIOLATION
    pg._conn.rollback()


def test_a_transaction_time_inside_the_bound_is_accepted(pg) -> None:
    """The positive control for the bound: an insert stamped a few seconds off --
    ordinary clock skew between an application host and a database host -- must
    still be accepted. Without this, the tests above would be equally satisfied by
    a trigger that rejected every insert."""
    tenant_id = _tenant(pg)
    pg._use_tenant(tenant_id)

    request_id = _raw_insert_pg(
        pg,
        tenant_id,
        decided_at=transaction_time() - timedelta(days=400),
        recorded_at=transaction_time() - timedelta(seconds=RECORDED_AT_TOLERANCE_SECONDS / 2),
        late_recording_reason=_BACKFILL,
    )
    assert len(pg.request_lifecycle(tenant_id, request_id)) == 1


def test_sqlite_bounds_the_transaction_time_too(sqlite_store) -> None:
    """The same bound on the demo engine, so a raw insert cannot assert a
    transaction time there either. The trigger uses `julianday('now')`, which is
    UTC, against the fixed-width stored form including its +00:00 offset."""
    tenant_id = _tenant(sqlite_store)
    payload = transition_payload(
        transition_id=new_id(RequestTransitionId), tenant_id=tenant_id,
        request_id=new_id(RequestId), from_state=ServiceRequestState.REQUESTED,
        to_state=ServiceRequestState.DENIED, decided_at=_utc(2020, 1, 1),
        recorded_at=_utc(2020, 1, 1, 0, 0, 1), actor_type="human",
        actor_id="dispatcher-token-7", reason_codes=(ReasonCode.NO_ACCESSIBLE_CAPACITY,),
        requested_window=None, negotiated_window=None, late_recording_reason=_BACKFILL,
    )
    with pytest.raises(sqlite3.IntegrityError, match="transaction time"):
        sqlite_store._conn.execute(
            f"INSERT INTO {_TABLE} (transition_id, tenant_id, request_id, sequence, "  # noqa: S608
            "from_state, to_state, decided_at, recorded_at, actor_type, actor_id, "
            "reason_codes, ingest_lag_seconds, late_recording_reason, prev_hash, hash) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                payload["transition_id"], str(tenant_id), payload["request_id"], 1,
                "requested", "denied", payload["decided_at"], payload["recorded_at"],
                "human", "dispatcher-token-7", '["NO_ACCESSIBLE_CAPACITY"]', 1.0,
                _BACKFILL.value, None,
                lifecycle_transition_hash(
                    prev_hash=None, payload=payload, sequence=1,
                    request_id=payload["request_id"],
                ),
            ),
        )
        sqlite_store._conn.commit()


# =========================================================================
# 5. LATE ARRIVAL IS DECLARED
# =========================================================================


def test_a_late_record_with_no_declared_reason_is_refused(sqlite_store) -> None:
    """A decision recorded weeks after it was made is legitimate. Recording it as
    though it were contemporaneous is not, and this is where that line is drawn.

    The error has its own type because the remedy is specific and is not "retry":
    somebody has to state which `LateRecordingReason` applies.
    """
    tenant_id = _tenant(sqlite_store)
    request_id = new_id(RequestId)

    with pytest.raises(UndeclaredLateRecordError):
        sqlite_store.record_transition(
            tenant_id=tenant_id, request_id=request_id,
            from_state=ServiceRequestState.REQUESTED, to_state=ServiceRequestState.DENIED,
            decided_at=_utc(2026, 7, 1, 9, 14, 3),
            actor_type="human", actor_id="dispatcher-token-7",
            reason_codes=(ReasonCode.NO_ACCESSIBLE_CAPACITY,),
        )
    assert sqlite_store.request_lifecycle(tenant_id, request_id) == ()


def test_a_prompt_record_may_not_claim_a_late_reason(sqlite_store) -> None:
    """The complement, and it has to exist or the rule above would be satisfiable
    by declaring BATCH_IMPORT on everything -- at which point the field stops
    carrying information and an auditor reading it learns nothing."""
    tenant_id = _tenant(sqlite_store)

    with pytest.raises(ValueError, match="must NOT name"):
        sqlite_store.record_transition(
            tenant_id=tenant_id, request_id=new_id(RequestId),
            from_state=ServiceRequestState.REQUESTED, to_state=ServiceRequestState.CANCELLED,
            decided_at=transaction_time() - timedelta(seconds=1),
            actor_type="human", actor_id="rider-token-3",
            late_reason=_BACKFILL,
        )


def test_the_measured_lag_is_stored_and_surfaced_in_the_explanation(sqlite_store) -> None:
    """"How late was this record?" is a column and a field of the explain view,
    not a subtraction each reader performs for themselves.

    It is on the EXPLANATION deliberately: a regulator shown only `decided_at`
    cannot tell a live capture from a backfill entered after a complaint was
    filed, and that difference is the difference between contemporaneous evidence
    and a reconstruction."""
    tenant_id = _tenant(sqlite_store)
    request_id = _record_denial(sqlite_store, tenant_id)

    (stored,) = sqlite_store.request_lifecycle(tenant_id, request_id)
    explanation = sqlite_store.explain_outcome(tenant_id, request_id)

    expected = (stored.recorded_at - stored.decided_at).total_seconds()
    assert stored.ingest_lag_seconds == pytest.approx(expected)
    assert explanation.ingest_lag_seconds == pytest.approx(expected)
    assert explanation.late_recording_reason is LateRecordingReason.BATCH_IMPORT
    assert explanation.recorded_at == stored.recorded_at
    assert explanation.ingest_lag_seconds > LIFECYCLE_LATE_ARRIVAL_THRESHOLD_SECONDS


def test_the_database_refuses_an_undeclared_late_row_written_by_raw_sql(pg) -> None:
    """The Python rule is application code. This one is a CHECK constraint, proved
    by reaching past every Python guard with raw SQL -- the same path the audit
    used."""
    tenant_id = _tenant(pg)
    pg._use_tenant(tenant_id)

    with pytest.raises(psycopg.errors.CheckViolation):
        _raw_insert_pg(
            pg,
            tenant_id,
            decided_at=transaction_time() - timedelta(days=3),
            late_recording_reason=None,
        )
    pg._conn.rollback()

    # POSITIVE CONTROL: the identical row, with the reason declared.
    pg._use_tenant(tenant_id)
    request_id = _raw_insert_pg(
        pg,
        tenant_id,
        decided_at=transaction_time() - timedelta(days=3),
        late_recording_reason=LateRecordingReason.INTEGRATION_OUTAGE,
    )
    assert len(pg.request_lifecycle(tenant_id, request_id)) == 1


def test_the_late_arrival_threshold_in_sql_matches_the_one_in_python() -> None:
    """Two declarations of one number can drift, and the drift is silent in the
    dangerous direction: a database threshold LOOSER than the application's would
    accept rows the application calls late with no explanation at all, written by
    any path that does not go through Python."""
    from pathlib import Path

    schema = (
        Path(__file__).resolve().parents[3]
        / "app" / "canonical" / "sql" / "schema_v0_1.sql"
    ).read_text(encoding="utf-8")

    clause = "CHECK (ingest_lag_seconds <= 300 OR late_recording_reason IS NOT NULL)"
    assert clause in schema, (
        "the late-arrival CHECK is not in the portable schema in the expected form"
    )
    assert LIFECYCLE_LATE_ARRIVAL_THRESHOLD_SECONDS == 300.0, (
        "LIFECYCLE_LATE_ARRIVAL_THRESHOLD_SECONDS has changed and the SQL CHECK has "
        "not -- the database would accept undeclared late rows the application refuses"
    )


def test_the_clock_tolerance_in_sql_matches_the_one_in_python() -> None:
    """The same drift guard for the transaction-time bound, over both engines'
    trigger files."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    sqlite_sql = (
        root / "app" / "canonical" / "sql" / "lifecycle_immutability_sqlite.sql"
    ).read_text(encoding="utf-8")
    bootstrap_sql = (
        root / "platform" / "infra" / "compose" / "initdb" / "02-lifecycle-ledger-bootstrap.sql"
    ).read_text(encoding="utf-8")
    fallback_sql = (
        root / "app" / "canonical" / "sql" / "lifecycle_immutability_postgres.sql"
    ).read_text(encoding="utf-8")

    assert RECORDED_AT_TOLERANCE_SECONDS == 60.0
    assert "* 86400.0 > 60.0" in sqlite_sql
    assert "IF skew_seconds > 60 THEN" in bootstrap_sql
    assert "IF skew_seconds > 60 THEN" in fallback_sql


# =========================================================================
# 6. THE HASH CHAIN
# =========================================================================


def test_a_recorded_chain_verifies(sqlite_store) -> None:
    """The positive control the rest of this section depends on: an untouched
    three-transition chain verifies, so a later failure means tampering and not a
    verifier that rejects everything."""
    tenant_id = _tenant(sqlite_store)
    request_id = new_id(RequestId)
    for from_state, to_state, minute in (
        (ServiceRequestState.REQUESTED, ServiceRequestState.NEGOTIATED, 3),
        (ServiceRequestState.NEGOTIATED, ServiceRequestState.SCHEDULED, 7),
        (ServiceRequestState.SCHEDULED, ServiceRequestState.IN_PROGRESS, 9),
    ):
        kwargs = {}
        if to_state is ServiceRequestState.NEGOTIATED:
            from app.canonical.lifecycle import TimeWindow

            kwargs = {
                "reason_codes": (ReasonCode.NO_ACCESSIBLE_CAPACITY,),
                "requested_window": TimeWindow(
                    start=_utc(2026, 7, 1, 8, 0), end=_utc(2026, 7, 1, 8, 30)
                ),
                "negotiated_window": TimeWindow(
                    start=_utc(2026, 7, 1, 9, 45), end=_utc(2026, 7, 1, 10, 15)
                ),
            }
        sqlite_store.record_transition(
            tenant_id=tenant_id, request_id=request_id,
            from_state=from_state, to_state=to_state,
            decided_at=_utc(2026, 7, 1, 9, 14, minute),
            actor_type="system", actor_id="scheduler",
            late_reason=_BACKFILL, **kwargs,
        )

    verification = sqlite_store.verify_request_lifecycle(tenant_id, request_id)
    assert verification.ok, verification.findings
    assert verification.rows_checked == 3

    rows = sqlite_store.raw_lifecycle_rows(tenant_id, request_id)
    assert rows[0]["prev_hash"] is None
    assert rows[1]["prev_hash"] == rows[0]["hash"]
    assert rows[2]["prev_hash"] == rows[1]["hash"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("actor_id", "forged-actor"),
        ("to_state", "completed"),
        ("reason_codes", "[]"),
        ("decided_at", "2020-01-01T00:00:00.000000+00:00"),
    ],
)
def test_a_row_whose_contents_were_changed_no_longer_matches_its_hash(field, value) -> None:
    """TAMPER EVIDENCE, tested where tampering is still possible: on the raw row
    mapping, not through a store that now refuses the UPDATE outright.

    That is deliberate and is the point of a chain existing at all. The database
    guards protect the live table; the chain is what catches a mutation made where
    those guards do not run -- an edited backup, a restore from a tampered dump, a
    replica that diverged, a row carried between systems. It is why the ledger's
    tamper-evidence and this record's are now the same construction.
    """
    store = SqliteCanonicalStore()
    try:
        tenant_id = _tenant(store)
        request_id = _record_denial(store, tenant_id)
        rows = store.raw_lifecycle_rows(tenant_id, request_id)
        assert verify_lifecycle_chain(rows).ok

        rows[0][field] = value
        verification = verify_lifecycle_chain(rows)

        assert not verification.ok, (
            f"changing {field} to {value!r} left the chain verifying -- that field is "
            "not covered by the hash, so it can be rewritten undetectably"
        )
        assert any("does not match its contents" in finding for finding in verification.findings)
    finally:
        store.close()


def test_a_tampered_row_cannot_be_read_back_as_a_record(sqlite_store) -> None:
    """The read path is the second half of the tamper story: a row whose hash does
    not match its contents raises rather than being handed back as history.

    Inserted by raw SQL because the triggers refuse the UPDATE -- which means this
    test is exercising the case where an attacker holds INSERT (which the
    deployment credential does hold) rather than the case where they hold UPDATE
    (which it does not).
    """
    tenant_id = _tenant(sqlite_store)
    request_id = new_id(RequestId)
    now = transaction_time()

    sqlite_store._conn.execute(
        f"INSERT INTO {_TABLE} (transition_id, tenant_id, request_id, sequence, "  # noqa: S608
        "from_state, to_state, decided_at, recorded_at, actor_type, actor_id, "
        "reason_codes, ingest_lag_seconds, hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            str(new_id(RequestTransitionId)), str(tenant_id), str(request_id), 1,
            "requested", "cancelled", iso_fixed_utc(now - timedelta(seconds=1)),
            iso_fixed_utc(now), "system", "scheduler", "[]", 1.0, "f" * 64,
        ),
    )
    sqlite_store._conn.commit()

    with pytest.raises(LifecycleChainError):
        sqlite_store.request_lifecycle(tenant_id, request_id)

    verification = sqlite_store.verify_request_lifecycle(tenant_id, request_id)
    assert not verification.ok


def test_an_appended_row_that_does_not_continue_the_chain_is_reported(pg) -> None:
    """WHAT THE CHAIN CATCHES WHEN THE ATTACKER HOLDS THE INSERT PRIVILEGE -- which
    the deployment credential does, by design, because appending is its job.

    There is no secret in the hash, so a forger with this source code can compute
    a valid one. What they CANNOT do is make the forged row continue the recorded
    history: this appends a second transition to a request whose chain is already
    terminal, with a perfectly-formed hash, and the verifier reports both the
    broken link and the state discontinuity.

    Stated plainly because it bounds the claim: a forger with INSERT can still
    append a WELL-FORMED transition to an in-flight request, and nothing here
    distinguishes that from a real one. Preventing that needs authentication --
    signed rows, or checkpoint roots anchored outside this database -- and this
    repository has neither.

    NOTE WHAT THE DATABASE ALREADY REFUSED BEFORE THE VERIFIER GOT A CHANCE, found
    while writing this test: an append with a NULL `prev_hash` at sequence 2 is
    rejected by the genesis CHECK, so a forger cannot simply omit the link. They
    must supply one -- which is what this test does, with a value that does not
    match the row it claims to follow.
    """
    tenant_id = _tenant(pg)
    request_id = _record_denial(pg, tenant_id)

    pg._use_tenant(tenant_id)
    _raw_insert_pg(
        pg, tenant_id, request_id=request_id, sequence=2,
        from_state=ServiceRequestState.SCHEDULED, to_state=ServiceRequestState.COMPLETED,
        decided_at=transaction_time() - timedelta(seconds=1), actor_id="forged-actor",
        prev_hash="0" * 64,
    )

    verification = pg.verify_request_lifecycle(tenant_id, request_id)
    assert not verification.ok
    findings = " | ".join(verification.findings)
    assert "does not link to the preceding row" in findings
    assert "does not continue the recorded history" in findings
