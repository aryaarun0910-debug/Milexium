"""MX-B-ADAPTER-REFS-009: the vehicle/run reference in the OTHER four adapters.

ADR-0054 closed the chain adapter -> `Outcome` -> store -> teardown for the
operator export, and named its own limitation: "This closes the chain for the
operator-export adapter only. The other adapters (TIDES, GTFS-Flex, TLC,
GTFS-Realtime) are unchanged; where they carry a vehicle reference it is still
unwired." This file is the answer, and the answer is not the same for all four.

WHAT EACH FORMAT ACTUALLY CARRIES -- established here, not assumed:

  TIDES trips_performed  vehicle_id AND block_id -- BOTH. Wired, and the chain
                         is pulled end to end through a real store.
  GTFS-Realtime          vehicle.id, and NO run/block reference at all. The
                         vehicle side was already wired when the observation
                         family landed (ADR-0031); what was never demonstrated
                         is that it survives to a teardown, which is proven
                         here. The absent run reference is RECORDED.
  GTFS-Flex              NEITHER. No vehicle field exists in the standard; the
                         optional trips.block_id is empty throughout the
                         acquired feed and is now measured per row rather than
                         assumed. Recorded, not wired, not synthesized.
  TLC FHVHV              NEITHER, and the three columns that look like one are
                         a company licence and two base stations. Recorded, and
                         a person-identifying column is REFUSED (see below).

WHY THE NEGATIVE ANSWERS ARE DELIVERABLES AND NOT GAPS. Deadhead is measurable
only by chaining ONE vehicle's consecutive trips (ADR-0039). A source with no
vehicle cannot produce that number at all, and the failure mode is not an error
-- it is a plausible number computed from the nearest-looking column, with no
missing value anywhere to warn the reader. `hvfhs_license_num` chains twenty
million Uber trips into one vehicle's day; `trip_id` chains each trip to itself
and reports zero deadhead. Both look fine. So each adapter records what it does
NOT have, and each has a test proving nothing adjacent is used instead.

THE TLC PII QUESTION, ANSWERED. A hack licence is a DRIVER's TLC licence number
-- a person, resolvable to a name through TLC's public licensee lookup -- and a
medallion is a permit held by a person or a small company. Neither is a vehicle.
Worse, the category error survives being careful about it: in an owner-operator
fleet, which is most of the for-hire trade, vehicle and driver are one-to-one,
so even a genuine vehicle id is a pseudonymous person id. `Outcome.vehicle_ref`
has no tokenisation and no redaction, and `VehicleSegment`'s own guard inspects
the COLUMN NAME a caller points at, so a person id laundered into the canonical
field upstream would pass it. The refusal therefore has to be at the adapter,
ahead of everything else, and section 4 tests the ORDER as the behaviour.

EVERY FIXTURE HERE IS SYNTHETIC OR PUBLIC OPEN DATA. No operator has sent
Milexium consented data; status is Demonstrated, never Validated (ADR-0001).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from themis.canonical import Outcome, Tenant, TenantId, VehicleObservation, new_id
from themis.canonical.postgres_storage import PostgresCanonicalStore
from themis.canonical.postgres_storage import is_reachable as pg_is_reachable
from themis.canonical.storage import SqliteCanonicalStore
from themis.connect.gtfs_flex import (
    NO_VEHICLE_REFERENCE_FIELD as FLEX_NO_VEHICLE_REFERENCE_FIELD,
)
from themis.connect.gtfs_flex import read_gtfs_flex_zip
from themis.connect.gtfs_realtime import NO_RUN_REFERENCE_FIELD
from themis.connect.tides_trips import (
    ENTITY_BEHIND_THE_LABEL_FIELD,
    TidesPerformedTrip,
)
from themis.connect.tlc_trips import (
    NO_VEHICLE_REFERENCE_FIELD as TLC_NO_VEHICLE_REFERENCE_FIELD,
)
from themis.connect.tlc_trips import PERSON_IDENTIFYING_COLUMNS, TlcTripsAdapter
from aletheia.replay.teardown import VehicleSegment, teardown_deadhead

from conformance.fixtures.builders_connect_gtfs_flex import (
    example_gtfs_flex_adapter,
    example_gtfs_flex_row,
)
from conformance.fixtures.builders_connect_gtfs_realtime import (
    example_gtfs_realtime_adapter,
    example_trip_update_stop_row,
    example_vehicle_position_row,
)
from conformance.fixtures.builders_connect_tides import (
    example_tides_adapter,
    example_tides_row,
)
from conformance.fixtures.builders_connect_tlc import example_tlc_adapter, example_tlc_row

FLEX_FEED_GLOB = "gtfs-flex-on-demand.*.zip"
STANDARDS_DIR = Path(__file__).parents[3] / "data" / "acquired" / "standards"


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _tenant(name: str) -> Tenant:
    return Tenant(tenant_id=new_id(TenantId), name=name, created_at=_utc(2026, 7, 25))


def _losses(result) -> dict[str, object]:
    return {loss.source_field: loss for loss in result.semantic_loss}


# =========================================================================
# 1. TIDES -- the one remaining source that carries BOTH references
# =========================================================================


def _performed(adapter, row: dict):
    result = adapter.parse_performed_trip(row)
    assert result.record is not None, f"fixture row was quarantined: {result.quarantine}"
    return result


def test_the_tides_vehicle_and_block_reach_the_canonical_outcome() -> None:
    """The wiring. `vehicle_id` -> `Outcome.vehicle_ref` and `block_id` ->
    `Outcome.run_ref`, verbatim. Before this, both were reported dropped on
    every row and the teardown had nothing to group by."""
    adapter, tenant_id = example_tides_adapter()

    record = _performed(adapter, example_tides_row()).record

    assert isinstance(record, TidesPerformedTrip)
    assert isinstance(record.outcome, Outcome)
    assert record.outcome.vehicle_ref == "VH-07"
    assert record.outcome.run_ref == "BLK-3"
    assert record.outcome.tenant_id == tenant_id
    assert record.outcome.served is True


def test_a_missing_block_is_never_backfilled_from_the_vehicle_number() -> None:
    """ADR-0054's `test_a_missing_run_reference_is_never_backfilled_from_the_
    vehicle_number`, for TIDES. A vehicle number is not a block id. Inventing
    one attributes empty time to a block that did not incur it -- the single
    error ADR-0039's `unattributable` bucket exists to prevent, and the one that
    looks tidiest in a report."""
    adapter, _ = example_tides_adapter()

    record = _performed(adapter, example_tides_row(block_id="")).record

    assert record.outcome.vehicle_ref == "VH-07"
    assert record.outcome.run_ref is None
    assert record.outcome.run_ref != record.outcome.vehicle_ref


def test_a_missing_vehicle_is_never_backfilled_from_the_block() -> None:
    """The mirror. A block id is not a vehicle number either: one block is
    worked by different vehicles on different days, so copying it across would
    merge distinct vehicles' work under one label."""
    adapter, _ = example_tides_adapter()

    record = _performed(adapter, example_tides_row(vehicle_id="")).record

    assert record.outcome.run_ref == "BLK-3"
    assert record.outcome.vehicle_ref is None


def test_a_blank_reference_is_none_and_never_the_empty_string() -> None:
    """`''` in a nullable TEXT column is a VALUE. It reads back later as a block
    somebody worked, and groups all such trips together under one empty name."""
    adapter, _ = example_tides_adapter()

    record = _performed(adapter, example_tides_row(vehicle_id="   ", block_id="")).record

    assert record.outcome.vehicle_ref is None
    assert record.outcome.run_ref is None
    assert "" not in (record.outcome.vehicle_ref, record.outcome.run_ref)


def test_the_operator_id_is_never_used_as_a_run_reference() -> None:
    """The tempting substitute nobody would notice. TIDES `operator_id` names
    the operating agency or the driver -- and a *run* is precisely one
    operator's assignment for a service day, so the two look interchangeable in
    a schema diagram. They are not: grouping by operator would put a driver's
    two blocks under one label and report the gap between them as deadhead one
    vehicle incurred. `RunPiece.operator_ref` already treats this field as a
    person reference; it must not become a vehicle chain key here."""
    adapter, _ = example_tides_adapter()

    record = _performed(adapter, example_tides_row(block_id="", vehicle_id="")).record

    assert record.outcome.run_ref is None
    assert record.outcome.vehicle_ref is None
    assert "OP-CENTRAL" not in str(record.outcome.model_dump())


def test_the_composite_and_the_outcome_cannot_disagree() -> None:
    """`TidesPerformedTrip` mirrors the refs for symmetry with
    `OperatorTripRecord`. Two copies of one fact must be set from one source."""
    adapter, _ = example_tides_adapter()

    for row in (
        example_tides_row(),
        example_tides_row(block_id=""),
        example_tides_row(vehicle_id=""),
        example_tides_row(vehicle_id="", block_id=""),
    ):
        record = _performed(adapter, row).record
        assert record.vehicle_ref == record.outcome.vehicle_ref
        assert record.run_ref == record.outcome.run_ref


def test_both_entry_points_produce_the_same_request() -> None:
    """The cost of having two entry points, bounded by test.
    `parse_performed_trip()` calls `parse()` and returns its request unmodified,
    so the ServiceRequest a caller gets cannot depend on which door they used.
    `request_id` is minted per call and is excluded; everything else must match."""
    adapter, _ = example_tides_adapter()
    row = example_tides_row()

    plain = adapter.parse(row).record
    composite = _performed(adapter, row).record.request

    assert plain.model_dump(exclude={"request_id"}) == composite.model_dump(
        exclude={"request_id"}
    )


def test_a_row_that_does_not_say_what_happened_is_quarantined_not_defaulted() -> None:
    """`Outcome.served` is a non-nullable bool. A row with no
    `actual_trip_start` and no cancellation does not say, so no honest value
    exists -- and defaulting either way writes an unreported fact into every
    total derived from it. `parse()` still accepts the row as a request."""
    adapter, _ = example_tides_adapter()
    row = example_tides_row(actual_trip_start="", schedule_relationship="scheduled")

    result = adapter.parse_performed_trip(row)

    assert result.is_quarantined
    assert result.record is None
    assert "does not say whether the trip was performed" in result.quarantine.reason
    assert result.quarantine.failed_field == "actual_trip_start"
    # The same row is still a perfectly good ServiceRequest.
    assert adapter.parse(row).record is not None


@pytest.mark.parametrize("spelling", ["canceled", "CANCELLED", "Canceled"])
def test_a_canceled_trip_is_not_recorded_as_served(spelling: str) -> None:
    """served=False, and no observed pickup even though the export left a
    timestamp in the column -- a cancelled trip has no pickup, and carrying the
    stale value across would make the cancellation invisible downstream."""
    adapter, _ = example_tides_adapter()

    record = _performed(adapter, example_tides_row(schedule_relationship=spelling)).record

    assert record.outcome.served is False
    assert record.outcome.actual_pickup_at is None
    # The reference still survives: which vehicle was assigned to a trip that
    # did not run is exactly the fact a deadhead teardown needs.
    assert record.outcome.vehicle_ref == "VH-07"
    assert record.outcome.run_ref == "BLK-3"


def test_the_reference_is_no_longer_reported_as_lost_on_the_performed_trip() -> None:
    """The defect ADR-0054 closed for the operator export, closed here. A loss
    list that keeps naming a field it actually persists teaches its reader to
    discount the whole list, which costs more than the record was worth."""
    adapter, _ = example_tides_adapter()

    losses = _losses(_performed(adapter, example_tides_row()))

    assert "vehicle_id" not in losses
    assert "block_id" not in losses
    assert not any(
        loss.source_value is not None and "VH-07" in loss.source_value
        for loss in losses.values()
    )


def test_what_legitimately_remains_lost_is_recorded_and_is_narrower() -> None:
    """NARROWED, not deleted. Deleting it is the easy move and silently drops a
    claim that is still true: the operator's LABEL persists, the entity it names
    does not, and the concrete cost is that a teardown sees the gaps between a
    block's trips but not the empty time before its first or after its last."""
    adapter, _ = example_tides_adapter()

    entry = _losses(_performed(adapter, example_tides_row()))[ENTITY_BEHIND_THE_LABEL_FIELD]

    assert entry.disposition == "dropped"
    assert entry.source_value is None
    # It states what IS retained, so it cannot be read as the record it replaced.
    assert "the reference itself is retained" in entry.reason
    assert "Outcome.vehicle_ref/Outcome.run_ref" in entry.reason
    # ...and names the concrete cost to the consumer that depends on it.
    assert "no foreign key to vehicles, blocks or run_pieces" in entry.reason
    assert "before its first trip" in entry.reason


def test_the_entity_gap_is_not_reported_when_the_row_named_no_reference() -> None:
    """The record is about an entity behind a label. With no label there is no
    such gap to report, and emitting it anyway would pad the loss list on the
    very rows whose real problem is that they carry nothing to chain."""
    adapter, _ = example_tides_adapter()

    losses = _losses(_performed(adapter, example_tides_row(vehicle_id="", block_id="")))

    assert ENTITY_BEHIND_THE_LABEL_FIELD not in losses


def test_the_served_judgment_is_recorded_as_a_coercion() -> None:
    """TIDES has no served column. The derivation is a modelling judgment, so it
    is reported as one rather than presented as a mapped field."""
    adapter, _ = example_tides_adapter()

    entry = _losses(_performed(adapter, example_tides_row()))["actual_trip_start"]

    assert entry.disposition == "coerced"
    assert "Outcome.served is materialised from this field" in entry.reason


def test_parse_still_reports_the_reference_as_dropped_but_says_why_narrowly() -> None:
    """`parse()` returns a ServiceRequest, and ADR-0043 deliberately gave
    vehicle_ref/run_ref a home on Outcome and NOT on ServiceRequest (one fact,
    one home). So `dropped` is still literally true for THAT output -- but the
    reason no longer claims a canonical gap that no longer exists, and points at
    the entry point that does carry it."""
    adapter, _ = example_tides_adapter()

    losses = _losses(adapter.parse(example_tides_row()))

    assert losses["vehicle_id"].disposition == "dropped"
    assert losses["block_id"].disposition == "dropped"
    for field in ("vehicle_id", "block_id"):
        assert "parse_performed_trip()" in losses[field].reason
    assert "Dropped from THIS output" in losses["vehicle_id"].reason


# =========================================================================
# 2. TIDES -- the chain, export row -> Outcome -> store -> teardown
# =========================================================================


@pytest.fixture(params=["sqlite", "postgres"])
def store(request):
    """Both engines through one fixture, the shape ADR-0054's own chain test
    uses: ADR-0004 claims the two expose the same method contract, and a chain
    proven on SQLite alone proves half of it. The PostgreSQL parameter skips
    cleanly when `milexium_dev` is unreachable -- but a skip proves nothing, so
    the packet report says which actually ran."""
    if request.param == "sqlite":
        st = SqliteCanonicalStore()
        try:
            yield st
        finally:
            st.close()
        return

    if not pg_is_reachable():
        pytest.skip("PostgreSQL (milexium_dev) is not reachable; skipping the PostgreSQL half")
    st = PostgresCanonicalStore.connect()
    try:
        yield st
    finally:
        st.drop_schema()
        st.close()


# Three trips on block BLK-3, then two on the SAME vehicle with a blank block --
# the adversarial shape for a back-fill, because a bug that copied the vehicle
# number (or the previous row's block) onto the blank rows would look entirely
# plausible on any fixture that used a different vehicle.
_TIDES_EXPORT = [
    example_tides_row(trip_id_performed="TP-1", actual_trip_start="2025-07-01T08:05:00"),
    example_tides_row(trip_id_performed="TP-2", actual_trip_start="2025-07-01T09:20:00"),
    example_tides_row(trip_id_performed="TP-3", actual_trip_start="2025-07-01T10:40:00"),
    example_tides_row(trip_id_performed="TP-4", actual_trip_start="2025-07-01T13:00:00", block_id=""),
    example_tides_row(trip_id_performed="TP-5", actual_trip_start="2025-07-01T14:00:00", block_id=""),
]


def _segments_from_stored_outcomes(outcomes: tuple[Outcome, ...]) -> list[VehicleSegment]:
    """Chain each block's consecutive trips into inter-trip segments using ONLY
    what came back out of the store. `None` is its own group.

    LABELLING CAVEAT, stated because the number depends on it: the whole
    inter-trip interval is labelled `deadhead`. That is a fixture choice to
    exercise the chain, NOT a claim the vehicle was empty for all of it -- TIDES
    does carry `actual_trip_end`, but this adapter does not map it (a dropoff
    belongs on an Outcome field that does not exist), so the revenue portion of
    each interval is unknown here. That is why these tests assert WHICH BLOCK the
    time is attributed to rather than treating the minutes as a measurement.
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


def test_the_tides_block_reference_survives_the_whole_chain_into_a_teardown(store) -> None:
    """THE DELIVERABLE FOR TIDES. TIDES row -> adapter -> `Outcome` ->
    MilexiumDB -> read back -> `VehicleSegment` -> `teardown_deadhead`, with
    nothing carried across in memory between the write and the read.

    Every reference is re-read from the store, so had the adapter not written
    the columns, every segment would be unattributable and the ranking empty --
    which is exactly the state ADR-0054 recorded for this adapter and nothing
    demonstrated end to end until now.
    """
    tenant = _tenant("tides-refs-chain")
    store.create_tenant(tenant)
    adapter, _ = example_tides_adapter()
    adapter = type(adapter)(tenant.tenant_id, recorded_at=_utc(2026, 7, 25, 12))

    for row in _TIDES_EXPORT:
        store.record_outcome(_performed(adapter, row).record.outcome)

    stored = store.outcomes(tenant.tenant_id)
    assert len(stored) == len(_TIDES_EXPORT)
    assert {o.run_ref for o in stored} == {"BLK-3", None}
    assert {o.vehicle_ref for o in stored} == {"VH-07"}

    result = teardown_deadhead(
        _segments_from_stored_outcomes(stored),
        dataset_label="TIDES trips_performed (open-spec fixture, MX-B-ADAPTER-REFS-009)",
        data_provenance="synthetic",
        run_ref_source="block_id, via Outcome.run_ref read back from MilexiumDB",
    )

    # 08:05 -> 09:20 -> 10:40 on BLK-3; 13:00 -> 14:00 unattributed.
    assert [(run.run_ref, run.deadhead_minutes) for run in result.top_runs] == [("BLK-3", 155.0)]
    assert result.top_runs[0].attributable is True
    assert result.top_runs[0].segment_count == 2
    assert result.attributed_run_count == 1
    assert result.total_deadhead_minutes == 215.0
    assert result.manifest.run_ref_source.startswith("block_id")


def test_the_tides_trips_whose_export_named_no_block_stay_unattributable(store) -> None:
    """The honesty half, and why the fixture reuses ONE vehicle: absence must
    survive the round trip as absence. A back-fill from the vehicle number, or
    from the neighbouring identified block, would move these 60 minutes into
    BLK-3's total and look entirely plausible in the report."""
    tenant = _tenant("tides-unattributable-chain")
    store.create_tenant(tenant)
    adapter, _ = example_tides_adapter()
    adapter = type(adapter)(tenant.tenant_id, recorded_at=_utc(2026, 7, 25, 12))

    for row in _TIDES_EXPORT:
        store.record_outcome(_performed(adapter, row).record.outcome)

    stored = store.outcomes(tenant.tenant_id)
    blank = [o for o in stored if o.run_ref is None]
    assert len(blank) == 2
    for outcome in blank:
        # Absent came back absent -- not '', not 'None', not the vehicle number.
        assert outcome.run_ref is None
        assert outcome.vehicle_ref == "VH-07"

    result = teardown_deadhead(
        _segments_from_stored_outcomes(stored),
        dataset_label="TIDES trips_performed (open-spec fixture)",
        data_provenance="synthetic",
        run_ref_source="block_id, via Outcome.run_ref read back from MilexiumDB",
    )

    assert result.unattributable is not None
    assert result.unattributable.run_ref is None
    assert result.unattributable.attributable is False
    assert result.unattributable.deadhead_minutes == 60.0
    assert {run.run_ref for run in result.top_runs} == {"BLK-3"}
    assert "VH-07" not in {run.run_ref for run in result.top_runs}


def test_a_tides_export_naming_no_block_at_all_is_wholly_unattributable(store) -> None:
    """The extreme of the same property: the teardown reports HOW MUCH empty
    time there was and not WHICH block incurred any of it. `top_runs` is empty
    and the whole total sits in `unattributable`, where truncating a ranking can
    never hide it."""
    tenant = _tenant("tides-no-block-at-all")
    store.create_tenant(tenant)
    adapter, _ = example_tides_adapter()
    adapter = type(adapter)(tenant.tenant_id, recorded_at=_utc(2026, 7, 25, 12))

    for started in ("2025-07-01T08:05:00", "2025-07-01T09:20:00"):
        row = example_tides_row(actual_trip_start=started)
        del row["block_id"]  # the column is not blank; it was never sent
        store.record_outcome(_performed(adapter, row).record.outcome)

    stored = store.outcomes(tenant.tenant_id)
    assert [o.run_ref for o in stored] == [None, None]

    result = teardown_deadhead(
        _segments_from_stored_outcomes(stored),
        dataset_label="TIDES trips_performed (open-spec fixture)",
        data_provenance="synthetic",
        run_ref_source="block_id, via Outcome.run_ref read back from MilexiumDB",
    )

    assert result.top_runs == ()
    assert result.attributed_run_count == 0
    assert result.unattributable is not None
    assert result.unattributable.deadhead_minutes == 75.0
    assert result.total_deadhead_minutes == 75.0


def test_the_tides_chain_carries_the_reference_and_not_the_rider(store) -> None:
    """Data minimisation across the handoff, asserted rather than assumed.
    `Outcome` has no rider field at all and TIDES's rider_ref is a synthetic
    per-row placeholder to begin with, so nothing rider-shaped can reach the
    store's outcome rows -- nor the teardown, which forbids extra fields on a
    `VehicleSegment` outright."""
    tenant = _tenant("tides-no-rider-through-chain")
    store.create_tenant(tenant)
    adapter, _ = example_tides_adapter()
    adapter = type(adapter)(tenant.tenant_id, recorded_at=_utc(2026, 7, 25, 12))

    record = _performed(adapter, example_tides_row()).record
    store.record_outcome(record.outcome)

    (stored,) = store.outcomes(tenant.tenant_id)
    assert record.request.rider_ref not in str(stored.model_dump())
    assert "OP-CENTRAL" not in str(stored.model_dump())
    assert stored.run_ref == "BLK-3"


# =========================================================================
# 3. GTFS-Realtime -- a vehicle reference, and NO run reference
# =========================================================================


def test_the_gtfs_realtime_vehicle_id_reaches_the_observation() -> None:
    """Already wired when the observation family landed (ADR-0031), asserted
    here as the anchor of the chain the rest of this section pulls on."""
    adapter, _ = example_gtfs_realtime_adapter()

    record = adapter.parse(example_vehicle_position_row()).record

    assert isinstance(record, VehicleObservation)
    assert record.vehicle_ref == "y1860"


@pytest.mark.parametrize(
    "adjacent",
    ["vehicle_label", "vehicle_license_plate", "trip_id", "entity_id"],
    ids=["label", "plate", "trip", "entity_id"],
)
def test_a_missing_gtfs_realtime_vehicle_is_never_backfilled(adjacent: str) -> None:
    """GTFS-RT's `vehicle` descriptor is OPTIONAL, so a trip-keyed position
    names no vehicle -- and four adjacent fields are sitting right there, each
    wrong in its own way. `vehicle_label` is a display string an agency may
    reuse across vehicles or blank; `license_plate` identifies a keeper, not a
    fleet unit; `trip_id` is one journey, not a vehicle; `entity_id` is a feed
    message key that merely happens to equal the vehicle id in some feeds and
    equals nothing in others. Absence must stay absent for all four."""
    adapter, _ = example_gtfs_realtime_adapter()
    row = example_vehicle_position_row(vehicle_license_plate="NY-1234")
    del row["vehicle_id"]

    record = adapter.parse(row).record

    assert record.vehicle_ref is None
    assert record.vehicle_ref != row[adjacent]


def test_gtfs_realtime_carries_no_run_reference_and_none_is_invented() -> None:
    """The recorded negative. GTFS-RT's TripDescriptor has no block field --
    `block_id` lives in STATIC GTFS trips.txt, which a realtime feed does not
    carry -- so run-level attribution is impossible from this source and says
    so, rather than being inferred from `trip_id`."""
    adapter, _ = example_gtfs_realtime_adapter()

    entry = _losses(adapter.parse(example_vehicle_position_row()))[NO_RUN_REFERENCE_FIELD]

    assert entry.disposition == "dropped"
    assert entry.source_value is None
    assert "block_id lives in STATIC GTFS trips.txt" in entry.reason
    # It must not read as "the vehicle reference was lost too".
    assert "VehicleObservation.vehicle_ref" in entry.reason
    # And it must name the failure mode of the obvious substitute.
    assert "zero deadhead" in entry.reason


def test_the_run_reference_absence_is_reported_even_when_a_vehicle_is_named() -> None:
    """A property of the FORMAT, not of the row. Reporting it only where it
    "looks" missing would make the absence invisible on exactly the well-formed
    feeds a consumer would trust most."""
    adapter, _ = example_gtfs_realtime_adapter()

    for row in (
        example_vehicle_position_row(),
        example_trip_update_stop_row(),
    ):
        assert NO_RUN_REFERENCE_FIELD in _losses(adapter.parse(row))


def test_a_trip_update_does_not_smuggle_the_vehicle_onto_the_stop_observation() -> None:
    """`StopTimeObservation` is stop-keyed and has no vehicle field, so the
    reference genuinely does not survive this mapping -- and the loss record now
    says that instead of implying it landed somewhere else. A predicted arrival
    is not evidence a vehicle was anywhere, so no vehicle-keyed record is minted
    from it either."""
    adapter, _ = example_gtfs_realtime_adapter()

    result = adapter.parse(example_trip_update_stop_row(vehicle_id="y1860"))

    assert "vehicle_ref" not in result.record.model_dump()
    assert "y1860" not in str(result.record.model_dump())
    entry = _losses(result)["vehicle_id"]
    assert entry.disposition == "dropped"
    assert entry.source_value == "y1860"
    assert "does NOT survive this mapping" in entry.reason


def test_a_licence_plate_never_reaches_a_gtfs_realtime_observation() -> None:
    """The GTFS-RT equivalent of the TLC question. `vehicle.license_plate` is
    an optional field real feeds do publish, and it identifies a registered
    keeper rather than a fleet unit. It must stay a reported loss and never be
    promoted into `vehicle_ref` on the grounds that it, too, identifies a
    vehicle."""
    adapter, _ = example_gtfs_realtime_adapter()

    result = adapter.parse(example_vehicle_position_row(vehicle_license_plate="NY-1234"))

    assert result.record.vehicle_ref == "y1860"
    assert "NY-1234" not in str(result.record.model_dump())
    assert _losses(result)["vehicle_license_plate"].disposition == "dropped"


@pytest.fixture
def observation_store():
    """The vehicle-observation store is PostgreSQL/PostGIS only -- there is no
    SQLite equivalent -- so this leg of the chain skips where the database is
    absent. Reported as a limitation rather than papered over."""
    from themis.canonical.observation_store import PostgisObservationStore
    from themis.canonical.observation_store import is_reachable as obs_reachable

    if not obs_reachable():
        pytest.skip("PostGIS observation store is not reachable; skipping the durable leg")
    st = PostgisObservationStore.connect()
    try:
        yield st
    finally:
        st.drop_schema()
        st.close()


_RT_FEED = [
    example_vehicle_position_row(vehicle_id="y1860", vehicle_timestamp=1690000000),
    example_vehicle_position_row(vehicle_id="y1860", vehicle_timestamp=1690003600),
    example_vehicle_position_row(vehicle_id="y1860", vehicle_timestamp=1690007200),
    # Two positions naming no vehicle at all (a trip-keyed feed), on the same
    # route, at the same times -- the shape a back-fill bug would survive.
    example_vehicle_position_row(vehicle_timestamp=1690000000, vehicle_id=None),
    example_vehicle_position_row(vehicle_timestamp=1690003600, vehicle_id=None),
]


def test_the_gtfs_realtime_vehicle_reference_persists_and_reaches_a_teardown(
    observation_store,
) -> None:
    """The chain for GTFS-RT: feed row -> adapter -> `VehicleObservation` ->
    PostGIS -> read back -> `VehicleSegment` -> `teardown_deadhead`.

    SEAM, STATED PLAINLY. The observation store's only read that returns a
    vehicle reference (`observations_within`) does not return `observed_at`, and
    adding a reader is outside this packet's owned paths. So the durable leg is
    proven by reading every reference back out of PostGIS and asserting it
    matches, and the teardown is then built from the observations. The two legs
    are joined by an assertion rather than by one continuous data path -- weaker
    than the TIDES chain above, and named rather than glossed.
    """
    tenant = _tenant("gtfs-rt-refs-chain")
    observation_store.create_tenant(tenant)
    adapter, _ = example_gtfs_realtime_adapter()
    adapter = type(adapter)(tenant.tenant_id, recorded_at=_utc(2026, 7, 25, 12))

    observations = []
    for row in _RT_FEED:
        record = adapter.parse(row).record
        observation_store.insert_vehicle_observation(record)
        observations.append(record)

    # The durable leg: what came back out of PostGIS, not what we put in.
    read_back = observation_store.observations_within(
        tenant.tenant_id, latitude=42.3311, longitude=-71.0905, radius_meters=500.0
    )
    assert len(read_back) == len(_RT_FEED)
    assert sorted(r["vehicle_ref"] or "" for r in read_back) == ["", "", "y1860", "y1860", "y1860"]
    # Absent came back absent, not '' and not the label '1860'.
    assert sum(1 for r in read_back if r["vehicle_ref"] is None) == 2
    assert "1860" not in {r["vehicle_ref"] for r in read_back}

    segments = []
    by_vehicle: dict[str | None, list[VehicleObservation]] = {}
    for observation in observations:
        by_vehicle.setdefault(observation.vehicle_ref, []).append(observation)
    for vehicle_ref, seen in by_vehicle.items():
        seen.sort(key=lambda o: o.observed_at)
        for earlier, later in zip(seen, seen[1:]):
            segment = VehicleSegment.from_row(
                {"started_at": earlier.observed_at, "ended_at": later.observed_at, "run_ref": vehicle_ref},
                kind="deadhead",
                started_at_column="started_at",
                ended_at_column="ended_at",
                run_ref_column="run_ref",
            )
            assert segment is not None
            segments.append(segment)

    result = teardown_deadhead(
        segments,
        dataset_label="GTFS-Realtime VehiclePositions (open public feed shape)",
        data_provenance="synthetic",
        # The manifest must say a VEHICLE was ranked, not a run: GTFS-RT has no
        # run, and a reader who assumed otherwise would compare this ranking
        # against a run-level one from another source.
        run_ref_source="vehicle.id, via VehicleObservation.vehicle_ref -- a VEHICLE, not a run",
    )

    assert [run.run_ref for run in result.top_runs] == ["y1860"]
    assert result.top_runs[0].segment_count == 2
    assert result.unattributable is not None
    assert result.unattributable.run_ref is None
    assert "a VEHICLE, not a run" in result.manifest.run_ref_source


# =========================================================================
# 4. TLC FHVHV -- no reference at all, and a person-identifying refusal
# =========================================================================


def test_fhvhv_carries_no_vehicle_or_run_reference_and_records_it() -> None:
    """The recorded negative, and the reason it is a deliverable rather than a
    TODO: no deadhead can be measured from this source AT ALL, and no better
    join would change that."""
    adapter, _ = example_tlc_adapter()

    entry = _losses(adapter.parse(example_tlc_row()))[TLC_NO_VEHICLE_REFERENCE_FIELD]

    assert entry.disposition == "dropped"
    assert entry.source_value is None
    assert "no hack licence, no medallion, no plate, no VIN" in entry.reason
    assert "the operating company's licence" in entry.reason
    assert "NO deadhead can be measured from this source" in entry.reason


def test_the_company_licence_is_reported_as_itself_and_never_as_a_reference() -> None:
    """`hvfhs_license_num` is the tempting substitute -- it is literally called
    a licence number, and it is populated on every row. It stays a `dropped`
    loss under its own name, described as the operator, and the absence record
    names it explicitly so a later reader cannot reach for it in good faith."""
    adapter, _ = example_tlc_adapter()

    losses = _losses(adapter.parse(example_tlc_row()))

    assert losses["hvfhs_license_num"].disposition == "dropped"
    assert losses["hvfhs_license_num"].source_value == "HV0003"
    assert "identifies the operating TNC" in losses["hvfhs_license_num"].reason
    assert "hvfhs_license_num" in losses[TLC_NO_VEHICLE_REFERENCE_FIELD].reason
    assert "dispatching_base_num" in losses[TLC_NO_VEHICLE_REFERENCE_FIELD].reason


@pytest.mark.parametrize(
    "column",
    ["hack_license", "Hack License", "medallion", "license_plate", "vin", "driver_id"],
)
def test_a_person_identifying_column_is_refused_and_its_value_is_not_retained(
    column: str,
) -> None:
    """The refusal, not a recommendation. A hack licence names a DRIVER and
    resolves to a name through TLC's public licensee lookup; a medallion names
    its holder; and in an owner-operator fleet a plate or VIN is one person's.
    None may become `Outcome.vehicle_ref`, which has no tokenisation and no
    redaction anywhere downstream of it -- so the row is refused, and the value
    is redacted from the quarantine record that preserves the row for re-run."""
    adapter, _ = example_tlc_adapter()

    result = adapter.parse(example_tlc_row(**{column: "5544321"}))

    assert result.is_quarantined
    assert result.record is None
    assert result.quarantine.failed_field == column
    assert "person-identifying column" in result.quarantine.reason
    assert "5544321" not in str(result.quarantine.model_dump())
    assert "a vehicle id IS a person id" in result.quarantine.reason


def test_the_person_identifying_gate_runs_before_every_other_check() -> None:
    """ORDER IS THE BEHAVIOUR, and a new field flowing through an adapter is
    exactly the change that quietly reorders a security check (ADR-0054 made the
    same assertion for the operator export). This row is BOTH missing every
    required column AND carrying a hack licence. Rejecting it as "missing
    request_datetime" would tell the sender to fix their timestamps and re-send
    the same identifiers."""
    adapter, _ = example_tlc_adapter()
    row = example_tlc_row(hack_license="5544321")
    for required in ("request_datetime", "PULocationID", "DOLocationID"):
        row[required] = None

    result = adapter.parse(row)

    assert result.is_quarantined
    assert result.quarantine.failed_field == "hack_license"
    assert "missing required field" not in result.quarantine.reason
    assert "5544321" not in str(result.quarantine.model_dump())


def test_the_general_adr_0051_classifier_still_runs_on_this_adapter_too() -> None:
    """The local for-hire-trade list does not REPLACE ADR-0051's classifier; it
    runs after it in the same gate. A rider name in a TLC extract is refused on
    the same ground it would be in an operator export."""
    adapter, _ = example_tlc_adapter()

    result = adapter.parse(example_tlc_row(rider_name="Jordan Ellery"))

    assert result.is_quarantined
    assert "personal name" in result.quarantine.reason
    assert "Jordan Ellery" not in str(result.quarantine.model_dump())


def test_the_real_published_fhvhv_columns_are_not_refused() -> None:
    """The other half of a fail-closed gate: it must not fail closed on the real
    data. All 25 columns of the published FHVHV schema -- verified against the
    parquet footers of the 2019-02 and 2026-05 files in data/curated/raw_tlc/ --
    must pass, or the adapter quarantines every row of a dataset that contains
    no identifier at all."""
    adapter, _ = example_tlc_adapter()
    row = example_tlc_row(cbd_congestion_fee=0.0)

    result = adapter.parse(row)

    assert not result.is_quarantined
    assert result.record is not None
    # And none of the three licence/base columns is on the refusal list.
    for column in ("hvfhs_license_num", "dispatching_base_num", "originating_base_num"):
        assert "".join(c for c in column.lower() if c.isalnum()) not in PERSON_IDENTIFYING_COLUMNS


# =========================================================================
# 5. GTFS-Flex -- neither reference, and the absence is MEASURED
# =========================================================================


def test_gtfs_flex_carries_no_vehicle_reference_and_records_it() -> None:
    """A feed describes bookable service. No vehicle has performed anything, so
    there is nothing to name -- and that is the finding, not a gap."""
    adapter, _ = example_gtfs_flex_adapter()

    entry = _losses(adapter.parse(example_gtfs_flex_row()))[FLEX_NO_VEHICLE_REFERENCE_FIELD]

    assert entry.disposition == "dropped"
    assert entry.source_value is None  # no block_id in the acquired feed's trip
    assert "GTFS-Flex has NO vehicle identifier anywhere in the standard" in entry.reason
    assert "trip_id, service_id or a booking_rule_id" in entry.reason


def test_a_populated_flex_block_id_is_reported_but_still_not_wired() -> None:
    """The absence is MEASURED, not assumed: a feed that does populate
    trips.block_id has it reported as the record's `source_value`. It is still
    not wired, and the reason says why -- this adapter emits a ServiceRequest,
    and attaching a block to a bookable window would assert that a vehicle
    worked a trip nobody has taken."""
    adapter, _ = example_gtfs_flex_adapter()

    result = adapter.parse(example_gtfs_flex_row(block_id="BLK-9"))

    entry = _losses(result)[FLEX_NO_VEHICLE_REFERENCE_FIELD]
    assert entry.source_value == "BLK-9"
    assert "a vehicle worked a trip nobody has taken" in entry.reason
    # It reached no canonical field, and did not leak in as a vendor extension.
    assert "BLK-9" not in str(result.record.model_dump())
    assert "block_id" not in {
        loss.source_field for loss in result.semantic_loss if loss.disposition == "unmapped_extension"
    }


def test_the_flex_trip_id_is_never_used_as_a_run_reference() -> None:
    """The substitute a reader reaches for when block_id is empty. A GTFS trip
    id names a published pattern, not a vehicle's day of work: keying on it
    would place each window in a run of its own and report zero deadhead between
    them -- a confident number, computed from nothing."""
    adapter, _ = example_gtfs_flex_adapter()

    result = adapter.parse(example_gtfs_flex_row())

    assert _losses(result)[FLEX_NO_VEHICLE_REFERENCE_FIELD].source_value is None
    assert "a trip id names a published pattern, not a vehicle's day of work" in (
        _losses(result)[FLEX_NO_VEHICLE_REFERENCE_FIELD].reason
    )
    assert not hasattr(result.record, "run_ref")
    assert not hasattr(result.record, "vehicle_ref")


def test_the_reader_measures_block_id_on_the_real_acquired_feed() -> None:
    """Against the REAL acquired feed rather than a fixture: every stop_times
    row carries a `block_id` key resolved through trips.txt, and it is None
    throughout -- so "GTFS-Flex has no run reference" is an observation about
    this feed and not a claim inherited from the specification text."""
    matches = sorted(STANDARDS_DIR.glob(FLEX_FEED_GLOB))
    if not matches:
        pytest.skip("the acquired GTFS-Flex feed is not present in this environment")

    rows = list(read_gtfs_flex_zip(matches[0]))

    assert rows, "the acquired feed yielded no stop_times rows"
    assert all("block_id" in row for row in rows)
    assert {row["block_id"] for row in rows} == {None}
