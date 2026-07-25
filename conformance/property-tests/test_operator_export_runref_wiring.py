"""MX-B-RUNREF-WIRING-008: the operator export's run reference, end to end.

WHY A NEW FILE RATHER THAN MORE OF `test_operator_export.py`. That file is
deliberately adapter-only -- it imports nothing but `packages.connect` and a
schema verifier, so a failure there is unambiguously an adapter failure. The
claim under test here is a CHAIN across four packages (connect -> canonical
entities -> canonical storage -> replay teardown) and needs a parametrized store
fixture. Mixing a storage fixture into the adapter's own conformance file would
make every future adapter test carry a database dependency it does not need.
The one edit made to that file instead is the single assertion that pinned the
`dropped` record this packet removes, and it says so in its docstring.

THE GAP THIS CLOSES. ADR-0038 shipped the adapter and surfaced that
`vehicle_ref`/`run_ref` had no canonical home, so the adapter recorded it as a
`dropped` semantic loss on EVERY row. ADR-0043 built the home -- two nullable
columns on `outcomes`, plus `record_outcome()`/`outcomes()` on both stores --
but `packages/connect` was outside that packet's owned paths, so the adapter
kept reporting as lost a field that by then persisted. Its own consequences
section says so: "Wiring the adapter through to the new column is a small
follow-up." This is that follow-up, and the wiring is the trivial half.

WHAT THE END-TO-END TEST BELOW ACTUALLY PROVES. Not that the two assignments
happen -- that is one line. It proves the *chain closes*: a synthetic export row
becomes an `Outcome` carrying the reference, is written to MilexiumDB, is read
back out, and the reference that comes back is enough to build a
`VehicleSegment` that `teardown_deadhead` attributes to the right run. Before
ADR-0043 the reference died at the process boundary; before this packet nothing
demonstrated the whole path in one place, and a chain that is proven only in
segments is a chain nobody has actually pulled on.

TWO HONESTY PROPERTIES, TESTED EXPLICITLY, NOT ASSUMED:

- **Absent stays absent.** ADR-0038 requires at least ONE of vehicle/run on
  intake, so the other is routinely missing. A row naming a vehicle but no run
  must round-trip with `run_ref is None` -- never back-filled from the vehicle
  number, never the empty string, never the string "None" -- and the teardown
  must report it under `unattributable` rather than folding it onto a
  neighbouring run. The fixture deliberately puts the unattributed trips on the
  SAME vehicle as the identified run, which is the shape a back-fill bug would
  survive undetected on any other fixture.
- **ADR-0051 is untouched.** The PII gate still fails closed ahead of every
  repair, and the graduated repairs still fire on the reference columns -- with
  the REPAIRED value reaching `Outcome.run_ref`, not the raw one.

EVERY FIXTURE HERE IS SYNTHETIC. No operator has sent Milexium any data; no row
below describes a real trip, rider, vehicle or agency (ADR-0038). Status:
Demonstrated, never operator-Validated.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from packages.canonical import Outcome, Tenant, TenantId, new_id
from packages.canonical.postgres_storage import PostgresCanonicalStore
from packages.canonical.postgres_storage import is_reachable as pg_is_reachable
from packages.canonical.storage import SqliteCanonicalStore
from packages.connect.operator_export import (
    OperatorExportAdapter,
    repair_rule_of,
)
from packages.replay.teardown import VehicleSegment, teardown_deadhead

RECORDED_AT = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)

DATASET_LABEL = "SYNTHETIC operator trip export (MX-B-RUNREF-WIRING-008 fixture)"
RUN_REF_SOURCE = "run_ref, via Outcome.run_ref read back from MilexiumDB"


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _tenant(name: str = "runref-wiring-conformance") -> Tenant:
    return Tenant(tenant_id=new_id(TenantId), name=name, created_at=_utc(2026, 7, 25))


def _row(
    trip_ref: str,
    pickup_at: str,
    *,
    vehicle_ref: str | object = "veh-7742",
    run_ref: str | object = "RUN-14A",
    **overrides: object,
) -> dict:
    """SYNTHETIC. One served trip in an export already using the canonical
    column names, so no `column_map` is needed and the mapping layer is not what
    is under test here."""
    row: dict = {
        "trip_ref": trip_ref,
        "requested_at": "2026-07-24T06:00:00+00:00",
        "scheduled_pickup_at": f"2026-07-25T{pickup_at}:00+00:00",
        "actual_pickup_at": f"2026-07-25T{pickup_at}:00+00:00",
        "pickup_zone": "Zone 12",
        "dropoff_zone": "Zone 4",
        "vehicle_ref": vehicle_ref,
        "run_ref": run_ref,
        "outcome": "served",
    }
    row.update(overrides)
    return row


def _parse(adapter: OperatorExportAdapter, row: dict):
    result = adapter.parse(row)
    assert result.record is not None, f"fixture row was quarantined: {result.quarantine}"
    return result


# =========================================================================
# 1. THE WIRING -- the reference reaches the canonical Outcome
# =========================================================================


def test_the_reference_is_written_onto_the_canonical_outcome() -> None:
    """ADR-0043's columns, populated by the adapter rather than left for the
    caller to copy across. Before this, `Outcome.vehicle_ref` was always None no
    matter what the export said."""
    tenant_id = new_id(TenantId)
    adapter = OperatorExportAdapter(tenant_id, recorded_at=RECORDED_AT)

    record = _parse(adapter, _row("T-1", "08:05")).record

    assert isinstance(record.outcome, Outcome)
    assert record.outcome.vehicle_ref == "veh-7742"
    assert record.outcome.run_ref == "RUN-14A"


@pytest.mark.parametrize(
    ("vehicle_ref", "run_ref", "expected_vehicle", "expected_run"),
    [
        ("veh-7742", "RUN-14A", "veh-7742", "RUN-14A"),  # the export named both
        ("veh-7742", "", "veh-7742", None),  # vehicle only -- ADR-0038 accepts this
        ("", "RUN-14A", None, "RUN-14A"),  # run only -- accepted too
    ],
)
def test_every_accepted_reference_shape_reaches_the_outcome_unaltered(
    vehicle_ref: str, run_ref: str, expected_vehicle: str | None, expected_run: str | None
) -> None:
    """The two-of-two, one-of-two and other-one-of-two shapes are all real
    exports. A blank column is ABSENT, not the empty string: `''` stored in a
    nullable TEXT column is a value that would later read back as a run nobody
    ran."""
    adapter = OperatorExportAdapter(new_id(TenantId), recorded_at=RECORDED_AT)

    record = _parse(
        adapter, _row("T-1", "08:05", vehicle_ref=vehicle_ref, run_ref=run_ref)
    ).record

    assert record.outcome.vehicle_ref == expected_vehicle
    assert record.outcome.run_ref == expected_run


def test_a_missing_run_reference_is_never_backfilled_from_the_vehicle_number() -> None:
    """The single most tempting wrong fix. A vehicle number is not a run id, and
    inventing one would attribute empty time to a run that did not incur it --
    the one error ADR-0039's `unattributable` bucket exists to prevent."""
    adapter = OperatorExportAdapter(new_id(TenantId), recorded_at=RECORDED_AT)

    record = _parse(adapter, _row("T-1", "08:05", run_ref="")).record

    assert record.outcome.vehicle_ref == "veh-7742"
    assert record.outcome.run_ref is None
    assert record.outcome.run_ref != record.outcome.vehicle_ref


def test_the_composite_and_the_outcome_cannot_disagree() -> None:
    """`OperatorTripRecord` keeps `vehicle_ref`/`run_ref` for callers written
    against ADR-0038, when it was the reference's only home. It is now the same
    fact twice, so the adapter must set both from one source; the outcome's is
    the copy that persists."""
    adapter = OperatorExportAdapter(new_id(TenantId), recorded_at=RECORDED_AT)

    for row in (_row("T-1", "08:05"), _row("T-2", "09:20", run_ref=""), _row("T-3", "10:40", vehicle_ref="")):
        record = _parse(adapter, row).record
        assert record.vehicle_ref == record.outcome.vehicle_ref
        assert record.run_ref == record.outcome.run_ref


# =========================================================================
# 2. THE SEMANTIC-LOSS REPORT -- a persisted field is not a lost field
# =========================================================================


def test_the_reference_is_no_longer_reported_as_lost() -> None:
    """The defect this packet closes. ADR-0038's record said the reference
    "would NOT survive a write to MilexiumDB"; since ADR-0043 it does, so the
    record was reporting a loss that no longer happens. A loss list that keeps
    naming a field it actually persists teaches its reader to discount the
    whole list, which costs more than the record was worth."""
    adapter = OperatorExportAdapter(new_id(TenantId), recorded_at=RECORDED_AT)

    result = _parse(adapter, _row("T-1", "08:05"))

    for loss in result.semantic_loss:
        assert "would NOT survive a write to MilexiumDB" not in loss.reason
        assert "no home for a vehicle/run assignment" not in loss.reason
    # The values themselves are no longer echoed into a loss record either.
    assert not any(
        loss.source_value is not None and "veh-7742" in loss.source_value
        for loss in result.semantic_loss
    )
    assert "vehicle_ref" not in {loss.source_field for loss in result.semantic_loss}
    assert "run_ref" not in {loss.source_field for loss in result.semantic_loss}


def test_what_legitimately_remains_lost_is_recorded_and_is_narrower() -> None:
    """The old record was not simply deleted. One clause of it is still true --
    "Vehicle exists as an entity, but the request-to-vehicle assignment does
    not" -- and it is kept, narrowed to exactly that: the operator's LABEL
    persists, the entity it names does not. `outcomes.vehicle_ref` carries no
    foreign key to `vehicles`/`blocks`/`run_pieces` (asserted directly in
    test_run_reference.py) and this adapter mints no such row, because the
    minimum field list carries nothing to build one from."""
    adapter = OperatorExportAdapter(new_id(TenantId), recorded_at=RECORDED_AT)

    losses = {loss.source_field: loss for loss in _parse(adapter, _row("T-1", "08:05")).semantic_loss}
    entry = losses["<the block, run or vehicle the reference names>"]

    assert entry.disposition == "dropped"
    assert entry.source_value is None
    # It states what IS retained, so the record cannot be read as the old one.
    assert "the reference itself is retained" in entry.reason
    assert "Outcome.vehicle_ref/Outcome.run_ref" in entry.reason
    # ...and names the concrete cost to the consumer that depends on it.
    assert "no foreign key to vehicles, blocks or run_pieces" in entry.reason
    assert "before its first trip" in entry.reason


def test_a_row_whose_export_named_no_run_still_reports_the_same_entity_gap() -> None:
    """The gap is about the reference being a label, so it does not disappear
    when only one of the two columns arrived."""
    adapter = OperatorExportAdapter(new_id(TenantId), recorded_at=RECORDED_AT)

    fields = {
        loss.source_field for loss in _parse(adapter, _row("T-1", "08:05", run_ref="")).semantic_loss
    }

    assert "<the block, run or vehicle the reference names>" in fields


# =========================================================================
# 3. THE CHAIN -- export row -> Outcome -> store -> read back -> teardown
# =========================================================================


@pytest.fixture(params=["sqlite", "postgres"])
def store(request):
    """Both engines through one fixture, the shape `test_run_reference.py` uses:
    ADR-0004's claim is that the two expose the same method contract, and a
    chain proven on SQLite alone would prove half of it. The PostgreSQL
    parameter skips cleanly when `milexium_dev` is unreachable so CI stays
    green -- but a skip proves nothing, so the packet reports which ran."""
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
            "skipping the PostgreSQL half of the run-reference chain"
        )
    st = PostgresCanonicalStore.connect()
    try:
        yield st
    finally:
        st.drop_schema()
        st.close()


# One synthetic export. Three trips worked by run RUN-14A, then two trips on the
# SAME vehicle whose run column is blank -- the adversarial shape for a
# back-fill, since a bug that copied the vehicle number (or the previous row's
# run) onto the blank rows would produce a plausible-looking result on any
# fixture that used a different vehicle.
_EXPORT_ROWS = [
    _row("T-1", "08:05"),
    _row("T-2", "09:20"),
    _row("T-3", "10:40"),
    _row("T-4", "13:00", run_ref=""),
    _row("T-5", "14:00", run_ref=""),
]


def _segments_from_stored_outcomes(outcomes: tuple[Outcome, ...]) -> list[VehicleSegment]:
    """Chain each run's consecutive trips into inter-trip segments, using ONLY
    what came back out of the store.

    Grouping key is `run_ref`, `None` being its own group -- exactly what a
    caller does when the teardown's `run_ref_source` is the run column. Within a
    group the trips are ordered by their observed pickup, because `outcomes()`
    orders by `request_id` (a UUIDv7 minted per row), not by time.

    LABELLING CAVEAT, stated because the number depends on it: the whole
    inter-trip interval is labelled `deadhead`. That is a fixture-level choice
    to exercise the chain, NOT a claim that the vehicle was empty for all of it
    -- the minimum field list carries no dropoff time, so the revenue portion of
    each interval is unknown. That is precisely the residual loss the adapter
    records, and it is why this test asserts on WHICH RUN the time is attributed
    to rather than treating the minutes as a measurement.
    """
    by_run: dict[str | None, list[Outcome]] = {}
    for outcome in outcomes:
        if outcome.actual_pickup_at is not None:
            by_run.setdefault(outcome.run_ref, []).append(outcome)

    segments: list[VehicleSegment] = []
    for run_ref, trips in by_run.items():
        trips.sort(key=lambda o: o.actual_pickup_at)
        for earlier, later in zip(trips, trips[1:]):
            segment = VehicleSegment.from_row(
                {
                    "started_at": earlier.actual_pickup_at,
                    "ended_at": later.actual_pickup_at,
                    "run_ref": run_ref,
                },
                kind="deadhead",
                started_at_column="started_at",
                ended_at_column="ended_at",
                run_ref_column="run_ref",
            )
            assert segment is not None
            segments.append(segment)
    return segments


def test_the_run_reference_survives_the_whole_chain_into_a_teardown(store) -> None:
    """THE DELIVERABLE. Export row -> adapter -> `Outcome` -> MilexiumDB ->
    read back -> `VehicleSegment` -> `teardown_deadhead`, with nothing carried
    across in memory between the write and the read.

    Every trip's reference is re-read from the store, so if the adapter had not
    written the columns the segments would all be unattributable and the run
    ranking would be empty -- which is exactly the state ADR-0038 described and
    nothing demonstrated end to end until now.
    """
    tenant = _tenant()
    store.create_tenant(tenant)
    adapter = OperatorExportAdapter(tenant.tenant_id, recorded_at=RECORDED_AT)

    for row in _EXPORT_ROWS:
        store.record_outcome(_parse(adapter, row).record.outcome)

    stored = store.outcomes(tenant.tenant_id)
    assert len(stored) == len(_EXPORT_ROWS)
    assert {o.run_ref for o in stored} == {"RUN-14A", None}
    assert {o.vehicle_ref for o in stored} == {"veh-7742"}

    result = teardown_deadhead(
        _segments_from_stored_outcomes(stored),
        dataset_label=DATASET_LABEL,
        data_provenance="synthetic",
        run_ref_source=RUN_REF_SOURCE,
    )

    # 08:05 -> 09:20 -> 10:40 on RUN-14A; 13:00 -> 14:00 unattributed.
    assert [(run.run_ref, run.deadhead_minutes) for run in result.top_runs] == [("RUN-14A", 155.0)]
    assert result.top_runs[0].attributable is True
    assert result.top_runs[0].segment_count == 2
    assert result.attributed_run_count == 1
    assert result.total_deadhead_minutes == 215.0

    # The manifest names what a "run" was in this export, so a reader can tell
    # what was ranked -- and here that provenance runs back to the store.
    assert result.manifest.run_ref_source == RUN_REF_SOURCE
    assert result.manifest.data_provenance == "synthetic"


def test_the_trips_whose_export_named_no_run_stay_unattributable(store) -> None:
    """The honesty half, and the reason the fixture reuses one vehicle: absence
    must survive the round trip as absence. A back-fill from the vehicle number,
    or from the neighbouring identified run, would move these 60 minutes into
    RUN-14A's total and look entirely plausible."""
    tenant = _tenant("unattributable-chain")
    store.create_tenant(tenant)
    adapter = OperatorExportAdapter(tenant.tenant_id, recorded_at=RECORDED_AT)

    for row in _EXPORT_ROWS:
        store.record_outcome(_parse(adapter, row).record.outcome)

    stored = store.outcomes(tenant.tenant_id)
    blank = [o for o in stored if o.run_ref is None]
    assert len(blank) == 2
    # Absent came back absent -- not '', not the string 'None', not the vehicle.
    for outcome in blank:
        assert outcome.run_ref is None
        assert outcome.vehicle_ref == "veh-7742"

    result = teardown_deadhead(
        _segments_from_stored_outcomes(stored),
        dataset_label=DATASET_LABEL,
        data_provenance="synthetic",
        run_ref_source=RUN_REF_SOURCE,
    )

    assert result.unattributable is not None
    assert result.unattributable.run_ref is None
    assert result.unattributable.attributable is False
    assert result.unattributable.deadhead_minutes == 60.0
    assert result.unattributable.segment_count == 1
    # Nothing fabricated a run id anywhere in the ranking.
    assert {run.run_ref for run in result.top_runs} == {"RUN-14A"}
    assert "veh-7742" not in {run.run_ref for run in result.top_runs}


def test_an_export_naming_no_run_at_all_produces_a_wholly_unattributable_teardown(store) -> None:
    """The extreme of the same property: every row names only a vehicle, so the
    teardown can report HOW MUCH empty time there was and not WHICH RUN incurred
    any of it. `top_runs` is empty and the whole total sits in `unattributable`,
    where truncating a ranking can never hide it."""
    tenant = _tenant("no-run-column-at-all")
    store.create_tenant(tenant)
    adapter = OperatorExportAdapter(tenant.tenant_id, recorded_at=RECORDED_AT)

    for trip_ref, pickup in (("T-1", "08:05"), ("T-2", "09:20")):
        row = _row(trip_ref, pickup, run_ref="")
        del row["run_ref"]  # the column is not merely blank; it was never sent
        store.record_outcome(_parse(adapter, row).record.outcome)

    stored = store.outcomes(tenant.tenant_id)
    assert [o.run_ref for o in stored] == [None, None]

    result = teardown_deadhead(
        _segments_from_stored_outcomes(stored),
        dataset_label=DATASET_LABEL,
        data_provenance="synthetic",
        run_ref_source=RUN_REF_SOURCE,
    )

    assert result.top_runs == ()
    assert result.attributed_run_count == 0
    assert result.unattributable is not None
    assert result.unattributable.deadhead_minutes == 75.0
    assert result.total_deadhead_minutes == 75.0


def test_the_chain_carries_the_reference_and_not_the_rider(store) -> None:
    """Data minimisation across the handoff, asserted rather than assumed. The
    adapter tokenises `rider_ref` onto the ServiceRequest and `Outcome` has no
    rider field at all, so nothing rider-shaped can reach the store's outcome
    rows or the teardown -- which forbids extra fields on a `VehicleSegment`
    outright."""
    tenant = _tenant("no-rider-through-the-chain")
    store.create_tenant(tenant)
    adapter = OperatorExportAdapter(tenant.tenant_id, recorded_at=RECORDED_AT)

    record = _parse(adapter, _row("T-1", "08:05", rider_ref="CL-88213")).record
    store.record_outcome(record.outcome)

    (stored,) = store.outcomes(tenant.tenant_id)
    assert "CL-88213" not in str(stored.model_dump())
    assert stored.run_ref == "RUN-14A"

    with pytest.raises(ValidationError):
        VehicleSegment(
            started_at=_utc(2026, 7, 25, 8, 5),
            ended_at=_utc(2026, 7, 25, 9, 20),
            kind="deadhead",
            run_ref="RUN-14A",
            rider_ref="CL-88213",
        )


# =========================================================================
# 4. ADR-0051 IS UNTOUCHED -- the gates the wiring runs behind
# =========================================================================


def test_the_pii_gate_still_fails_closed_ahead_of_the_new_wiring() -> None:
    """A row carrying a direct identifier is rejected on that ground even though
    it has a perfectly good run reference. The reference must never be the
    reason a PII row gets imported."""
    adapter = OperatorExportAdapter(new_id(TenantId), recorded_at=RECORDED_AT)

    result = adapter.parse(_row("T-1", "08:05", rider_name="Jordan Ellery"))

    assert result.is_quarantined
    assert result.record is None
    assert "personal name" in result.quarantine.reason
    assert "Jordan Ellery" not in str(result.quarantine.model_dump())


def test_a_repaired_reference_reaches_the_outcome_in_its_repaired_form() -> None:
    """The repair layer and the new wiring compose. A zero-width space in a
    vehicle column and a Parquet round-trip's `'412.0'` in a run column are both
    unambiguously repairable (ADR-0051); the value that lands on
    `Outcome.vehicle_ref`/`run_ref` must be the repaired one, and each repair
    must still be reported by its own rule."""
    adapter = OperatorExportAdapter(new_id(TenantId), recorded_at=RECORDED_AT)

    result = _parse(adapter, _row("T-1", "08:05", vehicle_ref="  veh-7742​", run_ref="412.0"))

    assert result.record.outcome.vehicle_ref == "veh-7742"
    assert result.record.outcome.run_ref == "412"
    rules = {repair_rule_of(loss) for loss in result.semantic_loss}
    assert "trim_whitespace" in rules
    assert "integral_float_identifier" in rules


def test_a_row_naming_neither_a_vehicle_nor_a_run_is_still_quarantined() -> None:
    """The wiring does not soften the intake gate. A trip that names neither
    cannot be chained at all, so it is refused rather than imported as a
    permanently unattributable row."""
    adapter = OperatorExportAdapter(new_id(TenantId), recorded_at=RECORDED_AT)

    result = adapter.parse(_row("T-1", "08:05", vehicle_ref="", run_ref=""))

    assert result.is_quarantined
    assert result.record is None
    assert "neither vehicle_ref nor run_ref is present" in result.quarantine.reason
    assert result.quarantine.failed_field == "vehicle_ref"
