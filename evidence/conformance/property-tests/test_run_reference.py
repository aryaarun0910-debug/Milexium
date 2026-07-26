"""Conformance tests for the canonical home of `vehicle_ref` / `run_ref`
(MX-A-RUNREF-PLATFORM-TENANT-004, task 1).

THE GAP THESE CLOSE. ADR-0038 shipped the operator trip-export adapter and
surfaced a real Program A hole in its own consequences section: the vehicle/run
reference had **no canonical home**. It was carried on the Connect-layer
`OperatorTripRecord` only and recorded as a `dropped` semantic loss on every
single row -- so it survived the in-memory handoff to the teardown and would
**not** have survived a write to MilexiumDB.

That is not a cosmetic omission. `app/replay/teardown.py` measures deadhead
by chaining ONE vehicle's consecutive trips, which is exactly why ADR-0038 makes
`vehicle_ref`-or-`run_ref` a mandatory intake column and quarantines a row that
names neither. The single field the entire teardown depends on could not be
persisted canonically.

The fix is deliberately small: two additive, nullable columns on the EXISTING
`outcomes` table plus matching fields on `Outcome` -- a run reference is an
attribute of an operational record, not an aggregate of its own, so it gets no
new entity and no new table. It lands on `outcomes` rather than
`service_requests` because which vehicle performed a trip is a fact about what
happened, and it sits beside `deadhead_minutes`, the field derived from chaining
it. One fact, one home, so the two can never disagree.

WHAT IS UNDER TEST, in three parts:

1. **Portability, asserted not assumed.** `schema_v0_1.sql` must run unmodified
   on SQLite (the demo engine) and PostgreSQL 17 (ADR-0002/0004), so an additive
   column is only safe if it stays inside the portable subset. The first section
   executes the file's actual bytes against a bare in-memory `sqlite3`
   connection -- no store class involved, so nothing can paper over a
   Postgres-only construct.
2. **The round trip, on BOTH engines.** Parametrized over `SqliteCanonicalStore`
   and `PostgresCanonicalStore` through one fixture, because the claim is that
   the two expose the same method contract (ADR-0004): a test that ran only on
   SQLite would prove half of it. The PostgreSQL parameter skips cleanly when
   `milexium_dev` is unreachable so CI stays green -- but a skip proves nothing,
   so the packet's evidence requirement is that it RUNS.
3. **The end of the ADR-0038 loss**, exercised through the real adapter.

SCOPE, stated rather than implied: this packet gives the reference a canonical
HOME and proves it durable. It does not change `app/connect/operator_export.py`
to populate `Outcome.vehicle_ref` directly -- that adapter is owned by Program C
and still emits its `dropped` semantic-loss record. The last test below shows the
handoff a caller can now make, which is the thing that was impossible before.

Status: Demonstrated only -- synthetic exports; no operator data exists in this
repository (ADR-0038).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.canonical import (
    Outcome,
    RequestId,
    Tenant,
    TenantId,
    new_id,
)
from app.canonical.postgres_storage import PostgresCanonicalStore
from app.canonical.postgres_storage import is_reachable as pg_is_reachable
from app.canonical.storage import SqliteCanonicalStore

_SCHEMA_PATH = Path("app/canonical/sql/schema_v0_1.sql")
_SCHEMA_SQL = (
    Path(__file__).resolve().parents[3] / "app" / "canonical" / "sql" / "schema_v0_1.sql"
).read_text(encoding="utf-8")

# The executable DDL only. The file's comments legitimately NAME the constructs
# that are banned from it -- they explain that geometry/GiST live in
# sql/postgis_postgres.sql instead -- so scanning the raw text would flag the very
# documentation that keeps the rule honest.
_SCHEMA_DDL = "\n".join(
    line.split("--", 1)[0] for line in _SCHEMA_SQL.splitlines()
).lower()


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _tenant(name: str = "run-reference-conformance") -> Tenant:
    return Tenant(tenant_id=new_id(TenantId), name=name, created_at=_utc(2026, 7, 24))


def _outcome(tenant_id: TenantId, **overrides) -> Outcome:
    fields = dict(
        tenant_id=tenant_id,
        request_id=new_id(RequestId),
        served=True,
        actual_pickup_at=_utc(2026, 7, 24, 8, 17),
        on_time=None,
        excess_ride_time_minutes=None,
        deadhead_minutes=None,
        vehicle_ref="veh-7742",
        run_ref="RUN-14A",
    )
    fields.update(overrides)
    return Outcome(**fields)


# =========================================================================
# 1. PORTABILITY -- the portable DDL must stay portable
# =========================================================================


def test_schema_v0_1_executes_unmodified_on_a_bare_sqlite_connection() -> None:
    """The load-bearing portability proof, and the reason it uses raw `sqlite3`
    rather than `SqliteCanonicalStore`: the store could in principle preprocess
    the file, so running the file's own bytes through a plain connection is what
    actually shows a Postgres-only construct did not sneak in with the new
    columns. `schema_v0_1.sql` is the file both engines load unmodified
    (ADR-0002/0004); `rls_postgres.sql` is where Postgres-only DDL belongs.
    """
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(_SCHEMA_SQL)  # raises if anything here is not portable
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        conn.close()

    assert "outcomes" in tables
    assert "tenants" in tables


def test_run_reference_columns_exist_and_are_nullable_on_sqlite() -> None:
    """Additive and NULLABLE, both asserted. NOT NULL would have been a breaking
    change to every existing `outcomes` writer, and it would also be wrong: an
    export that named neither a vehicle nor a run is *unattributable*, which the
    teardown reports as such instead of guessing it onto a neighbouring run.
    """
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(_SCHEMA_SQL)
        columns = {row[1]: row for row in conn.execute("PRAGMA table_info(outcomes)")}
    finally:
        conn.close()

    for name in ("vehicle_ref", "run_ref"):
        assert name in columns, f"{name} is missing from the outcomes table"
        _, _, declared_type, not_null, default, _ = columns[name]
        assert declared_type == "TEXT", f"{name} should be portable TEXT, got {declared_type!r}"
        assert not_null == 0, f"{name} must stay nullable"
        assert default is None, f"{name} must not invent a default value"


def test_run_reference_is_not_a_foreign_key_to_the_vehicles_table() -> None:
    """These name the SOURCE system's vehicle/run, not a Milexium `Vehicle`
    aggregate -- the same judgment `vehicle_observations.vehicle_ref` makes. An
    FK here would force every operator export to first mint canonical `Vehicle`
    rows it has no data for, and would reject a perfectly good run reference.
    """
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(_SCHEMA_SQL)
        referenced = {row[2] for row in conn.execute("PRAGMA foreign_key_list(outcomes)")}
    finally:
        conn.close()

    assert referenced == {"tenants"}, (
        "outcomes should reference only tenants; a foreign key from a source-system "
        f"reference to a canonical aggregate would be a category error (found {referenced})"
    )


@pytest.mark.parametrize(
    "construct",
    ["jsonb", "serial", "geometry", "timestamptz", "generated always", "gist", "on conflict"],
)
def test_portable_schema_contains_no_postgres_only_construct(construct: str) -> None:
    """A regression guard on the file's whole DDL, not just the columns this
    packet added: the SQLite execution above proves today's file runs, and this
    names the specific constructs that would break it, so a future edit fails
    with a readable reason rather than an opaque `sqlite3.OperationalError`.
    """
    assert construct not in _SCHEMA_DDL, (
        f"{_SCHEMA_PATH.as_posix()} contains the Postgres-only construct {construct!r}; "
        "it must run unmodified on SQLite -- Postgres-only DDL belongs in "
        "sql/rls_postgres.sql or sql/postgis_postgres.sql"
    )


# =========================================================================
# 2. ROUND TRIP -- both engines, one contract
# =========================================================================


@pytest.fixture(params=["sqlite", "postgres"])
def store(request):
    """The same tests, both engines. `params` (not two copies of each test) is
    what makes "identical method contract" a property under test rather than a
    claim in a docstring -- the same fixture shape
    evidence/conformance/property-tests/test_decision_alternatives.py uses."""
    if request.param == "sqlite":
        st = SqliteCanonicalStore()
        try:
            yield st
        finally:
            st.close()
        return

    if not pg_is_reachable():
        pytest.skip(
            "PostgreSQL (milexium_dev) is not reachable on this machine; "
            "skipping the PostgreSQL half of the run-reference contract"
        )
    st = PostgresCanonicalStore.connect()
    try:
        yield st
    finally:
        st.drop_schema()
        st.close()


def test_run_reference_round_trips_with_every_field_intact(store) -> None:
    """The core proof, and the exact thing ADR-0038 said was impossible: the
    vehicle/run reference survives a write to MilexiumDB and a read back.
    Equality is asserted on the whole reconstructed entity, so a stored column
    that no longer validates as an `Outcome` fails here rather than later."""
    tenant = _tenant()
    store.create_tenant(tenant)

    outcome = _outcome(tenant.tenant_id)
    store.record_outcome(outcome)

    assert store.outcomes(tenant.tenant_id) == (outcome,)


@pytest.mark.parametrize(
    ("vehicle_ref", "run_ref"),
    [
        ("veh-7742", "RUN-14A"),  # the export named both
        ("veh-7742", None),  # vehicle only -- ADR-0038 accepts this
        (None, "RUN-14A"),  # run only -- ADR-0038 accepts this too
        (None, None),  # neither: unattributable, and honoured as absent
    ],
)
def test_each_run_reference_shape_survives_a_read_back(
    store, vehicle_ref: str | None, run_ref: str | None
) -> None:
    """ADR-0038 requires at least ONE of the two on intake, so all three
    populated shapes are real and must persist. The (None, None) case is the one
    that matters most for honesty: absent must come back absent -- never `''`,
    never the string `'None'`, never back-filled from the other column. A
    fabricated run reference would silently attribute empty time to a run that
    did not incur it."""
    tenant = _tenant()
    store.create_tenant(tenant)

    outcome = _outcome(tenant.tenant_id, vehicle_ref=vehicle_ref, run_ref=run_ref)
    store.record_outcome(outcome)

    (stored,) = store.outcomes(tenant.tenant_id)
    assert stored.vehicle_ref == vehicle_ref
    assert stored.run_ref == run_ref
    assert stored == outcome


def test_deadhead_minutes_and_the_run_reference_it_came_from_coexist(store) -> None:
    """The whole point of putting the reference on `outcomes`: a teardown chains
    a vehicle's consecutive trips to derive `deadhead_minutes` and can now write
    that answer back beside the reference it was derived from, in one row."""
    tenant = _tenant()
    store.create_tenant(tenant)

    outcome = _outcome(tenant.tenant_id, deadhead_minutes=12.5, excess_ride_time_minutes=4.0)
    store.record_outcome(outcome)

    (stored,) = store.outcomes(tenant.tenant_id)
    assert stored.deadhead_minutes == 12.5
    assert stored.run_ref == "RUN-14A"


def test_on_time_stays_none_rather_than_collapsing_to_false(store) -> None:
    """A nullable BOOLEAN stored as portable INTEGER is the classic place a
    three-valued field silently becomes two-valued. ADR-0038 leaves `on_time`
    None because the on-time window is a policy parameter no export carries, so
    a None that read back as False would turn "we cannot say" into "it was
    late" -- a fabricated measurement."""
    tenant = _tenant()
    store.create_tenant(tenant)

    store.record_outcome(_outcome(tenant.tenant_id, on_time=None))
    (stored,) = store.outcomes(tenant.tenant_id)
    assert stored.on_time is None

    store.record_outcome(_outcome(tenant.tenant_id, on_time=False))
    assert {o.on_time for o in store.outcomes(tenant.tenant_id)} == {None, False}


def test_outcome_read_is_tenant_scoped(store) -> None:
    """The tenant filter is applied in SQL, never in Python after an unfiltered
    fetch. Two operators can legitimately use the SAME request id (it is only
    unique per tenant) and the same vehicle number, so this must separate them
    on tenant alone."""
    tenant_a = _tenant("a")
    tenant_b = _tenant("b")
    store.create_tenant(tenant_a)
    store.create_tenant(tenant_b)

    shared_request_id = new_id(RequestId)
    store.record_outcome(_outcome(tenant_a.tenant_id, request_id=shared_request_id))
    store.record_outcome(
        _outcome(tenant_b.tenant_id, request_id=shared_request_id, run_ref="RUN-OTHER")
    )

    a_rows = store.outcomes(tenant_a.tenant_id)
    assert len(a_rows) == 1
    assert a_rows[0].tenant_id == tenant_a.tenant_id
    assert a_rows[0].run_ref == "RUN-14A"


def test_outcomes_are_returned_in_request_id_order(store) -> None:
    """Both stores write the same ORDER BY, so the two engines return the same
    SEQUENCE, not merely the same set -- the property that keeps them from
    drifting into "equivalent but different" implementations."""
    tenant = _tenant()
    store.create_tenant(tenant)

    request_ids = sorted(str(new_id(RequestId)) for _ in range(3))
    for request_id in reversed(request_ids):
        store.record_outcome(_outcome(tenant.tenant_id, request_id=RequestId(request_id)))

    assert [str(o.request_id) for o in store.outcomes(tenant.tenant_id)] == request_ids


# =========================================================================
# 3. THE ADR-0038 LOSS, exercised through the real adapter
# =========================================================================


def test_operator_trip_record_run_reference_now_has_somewhere_to_land(store) -> None:
    """End to end on the exact gap ADR-0038 recorded.

    The adapter (read-only here -- `app/connect` is owned by Program C and
    is deliberately not modified by this packet) still returns the reference on
    the Connect-layer composite and still records its `dropped` semantic loss.
    What changed is that a caller can now carry it onto the canonical `Outcome`
    and persist it. Before these columns existed, this handoff had no
    destination and the reference died at the process boundary.
    """
    from app.connect.operator_export import OperatorExportAdapter

    tenant = _tenant("operator-handoff")
    store.create_tenant(tenant)

    adapter = OperatorExportAdapter(tenant.tenant_id, recorded_at=_utc(2026, 7, 24, 12))
    result = adapter.parse(
        {
            "trip_ref": "BK-90211",
            "requested_at": "2026-07-24T07:40:00+00:00",
            "scheduled_pickup_at": "2026-07-24T08:15:00+00:00",
            "actual_pickup_at": "2026-07-24T08:17:00+00:00",
            "pickup_zone": "Zone 12",
            "dropoff_zone": "Zone 4",
            "vehicle_ref": "veh-7742",
            "run_ref": "RUN-14A",
            "outcome": "served",
        }
    )
    assert result.record is not None, f"fixture row was quarantined: {result.quarantine}"
    record = result.record

    persisted = record.outcome.model_copy(
        update={"vehicle_ref": record.vehicle_ref, "run_ref": record.run_ref}
    )
    store.record_outcome(persisted)

    (stored,) = store.outcomes(tenant.tenant_id)
    assert stored.vehicle_ref == "veh-7742"
    assert stored.run_ref == "RUN-14A"
    assert stored.request_id == record.request.request_id
