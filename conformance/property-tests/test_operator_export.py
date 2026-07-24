"""Conformance for packages/connect/operator_export.py -- the operator trip
intake path described by docs/OPERATOR_DATA_INTAKE.md.

EVERY FIXTURE IN THIS FILE IS SYNTHETIC. No operator has sent Milexium any
data; none of these rows describes a real trip, a real rider, a real vehicle,
or a real agency. The two shapes below were written by hand to be structurally
different from each other (a wide vendor-style export needing a column_map, and
a minimal export already using the canonical names) so the adapter cannot be
overfitted to one vendor's header.

The headline behaviour proved here is the PII rejection path: an export
carrying a name/email/phone/address/national-or-medical-id column is
QUARANTINED with a reason naming the offending column, and the offending value
is redacted out of the preserved row -- not imported with the column ignored.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from packages.canonical import (
    Outcome,
    ServiceRequest,
    ServiceRequestState,
    TenantId,
    new_id,
)
from packages.connect.adapter import QuarantinedRow, parse_batch
from packages.connect.operator_export import (
    CANONICAL_COLUMNS,
    OUTCOME_VALUES,
    REDACTION_MARKER,
    REQUIRED_COLUMNS,
    VEHICLE_OR_RUN_COLUMNS,
    OperatorExportAdapter,
    OperatorTripRecord,
    classify_pii_column,
    looks_like_street_address,
)
from packages.verify import verify_against_schema

RECORDED_AT = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)

INTAKE_DOC = Path(__file__).parents[2] / "docs" / "OPERATOR_DATA_INTAKE.md"


# ---------------------------------------------------------------------------
# SYNTHETIC fixture 1: a wide vendor-style export.
#
# Shape: 18 columns, vendor-specific header names, mixed capitalisation and
# spaces, extra columns Milexium does not ask for, timestamps carrying an
# explicit offset. Requires a column_map. Nothing here is real.
# ---------------------------------------------------------------------------

WIDE_VENDOR_COLUMN_MAP = {
    "BookingNo": "trip_ref",
    "ClientKey": "rider_ref",
    "Booked On": "requested_at",
    "PromisedPickup": "scheduled_pickup_at",
    "ActualPickup": "actual_pickup_at",
    "PU Zone": "pickup_zone",
    "DO Zone": "dropoff_zone",
    "UnitNo": "vehicle_ref",
    "ManifestId": "run_ref",
    "TripStatus": "outcome",
}


def wide_vendor_row(**overrides: object) -> dict:
    """SYNTHETIC. One row of an imagined vendor's paratransit trip extract."""
    row = {
        "BookingNo": "BK-100244",
        "ClientKey": "CL-88213",
        "Booked On": "2026-03-02T14:05:00-05:00",
        "PromisedPickup": "2026-03-04T08:15:00-05:00",
        "ActualPickup": "2026-03-04T08:22:00-05:00",
        "PU Zone": "ZONE-NW-3",
        "DO Zone": "ZONE-CBD-1",
        "UnitNo": "UNIT-412",
        "ManifestId": "RUN-2026-03-04-A",
        "TripStatus": "Completed",
        # Extra vendor columns Milexium does not ask for:
        "FareType": "ADA-fixed",
        "ProviderCode": "SUBCON-2",
        "route_name": "Northwest Feeder",
        "TripMiles": "6.4",
        "SchedulingSystem": "VendorSuite 7.2",
        "ExportBatch": "2026-03-31-full",
        "OnTimeFlagVendor": "Y",
        "Notes": "curb pickup",
    }
    row.update(overrides)
    return row


def wide_vendor_adapter() -> tuple[OperatorExportAdapter, TenantId]:
    tenant_id = new_id(TenantId)
    return (
        OperatorExportAdapter(
            tenant_id, recorded_at=RECORDED_AT, column_map=dict(WIDE_VENDOR_COLUMN_MAP)
        ),
        tenant_id,
    )


# ---------------------------------------------------------------------------
# SYNTHETIC fixture 2: a minimal export.
#
# Shape: exactly the canonical column names, no column_map, no extra columns,
# no rider identifier at all (the state the intake document asks for), naive
# timestamps, a run reference but no vehicle reference. Nothing here is real.
# ---------------------------------------------------------------------------


def minimal_row(**overrides: object) -> dict:
    """SYNTHETIC. The smallest export the intake document accepts."""
    row = {
        "trip_ref": "T-0001",
        "requested_at": "2026-03-02T19:05:00",
        "scheduled_pickup_at": "2026-03-04T13:15:00",
        "actual_pickup_at": "2026-03-04T13:22:00",
        "pickup_zone": "NW3",
        "dropoff_zone": "CBD1",
        "run_ref": "RUN-A",
        "outcome": "served",
    }
    row.update(overrides)
    return row


def minimal_adapter() -> tuple[OperatorExportAdapter, TenantId]:
    tenant_id = new_id(TenantId)
    return OperatorExportAdapter(tenant_id, recorded_at=RECORDED_AT), tenant_id


# ---------------------------------------------------------------------------
# The published field list
# ---------------------------------------------------------------------------


def test_minimum_field_list_is_exactly_what_the_packet_asks_for() -> None:
    """trip/booking ref, requested/scheduled/actual times, pickup+dropoff zone,
    vehicle or run ref, outcome -- plus an optional tokenised rider ref."""

    assert set(CANONICAL_COLUMNS) == {
        "trip_ref",
        "rider_ref",
        "requested_at",
        "scheduled_pickup_at",
        "actual_pickup_at",
        "pickup_zone",
        "dropoff_zone",
        "vehicle_ref",
        "run_ref",
        "outcome",
    }
    assert REQUIRED_COLUMNS == (
        "trip_ref",
        "requested_at",
        "scheduled_pickup_at",
        "pickup_zone",
        "dropoff_zone",
        "outcome",
    )
    assert VEHICLE_OR_RUN_COLUMNS == ("vehicle_ref", "run_ref")
    assert OUTCOME_VALUES == ("served", "no_show", "denied", "cancelled")
    # No address-shaped column is ever asked for.
    assert not any("address" in column for column in CANONICAL_COLUMNS)


# ---------------------------------------------------------------------------
# Both synthetic shapes map cleanly
# ---------------------------------------------------------------------------


def test_wide_vendor_row_maps_to_schema_valid_canonical_records() -> None:
    adapter, tenant_id = wide_vendor_adapter()

    result = adapter.parse(wide_vendor_row())

    assert not result.is_quarantined
    record = result.record
    assert isinstance(record, OperatorTripRecord)
    assert isinstance(record.request, ServiceRequest)
    assert isinstance(record.outcome, Outcome)
    assert record.request.tenant_id == tenant_id
    assert record.request.pickup_zone == "ZONE-NW-3"
    assert record.request.dropoff_zone == "ZONE-CBD-1"
    assert record.request.status == ServiceRequestState.COMPLETED
    assert record.outcome.served is True
    assert record.outcome.request_id == record.request.request_id
    assert record.vehicle_ref == "UNIT-412"
    assert record.run_ref == "RUN-2026-03-04-A"
    # -05:00 offsets converted honestly to UTC.
    assert record.request.times.scheduled_pickup_at.isoformat() == "2026-03-04T13:15:00+00:00"
    assert record.request.times.actual_pickup_at.isoformat() == "2026-03-04T13:22:00+00:00"

    assert verify_against_schema(record.request.model_dump(mode="json"), ServiceRequest) == []
    assert verify_against_schema(record.outcome.model_dump(mode="json"), Outcome) == []


def test_minimal_row_maps_to_schema_valid_canonical_records() -> None:
    adapter, tenant_id = minimal_adapter()

    result = adapter.parse(minimal_row())

    assert not result.is_quarantined
    record = result.record
    assert record.request.tenant_id == tenant_id
    assert record.request.pickup_zone == "NW3"
    assert record.request.status == ServiceRequestState.COMPLETED
    assert record.outcome.served is True
    assert record.vehicle_ref is None
    assert record.run_ref == "RUN-A"

    assert verify_against_schema(record.request.model_dump(mode="json"), ServiceRequest) == []
    assert verify_against_schema(record.outcome.model_dump(mode="json"), Outcome) == []


def test_two_structurally_different_exports_of_the_same_trip_agree() -> None:
    """The anti-overfitting check: a wide vendor row and a minimal row that
    describe the same underlying trip must produce the same canonical facts,
    despite sharing not one column name."""

    wide, _ = wide_vendor_adapter()
    minimal, _ = minimal_adapter()

    wide_record = wide.parse(wide_vendor_row(**{"PU Zone": "NW3", "DO Zone": "CBD1"})).record
    minimal_record = minimal.parse(minimal_row()).record

    assert wide_record.request.times.requested_at == minimal_record.request.times.requested_at
    assert (
        wide_record.request.times.scheduled_pickup_at
        == minimal_record.request.times.scheduled_pickup_at
    )
    assert wide_record.request.times.actual_pickup_at == minimal_record.request.times.actual_pickup_at
    assert wide_record.request.pickup_zone == minimal_record.request.pickup_zone
    assert wide_record.request.dropoff_zone == minimal_record.request.dropoff_zone
    assert wide_record.request.status == minimal_record.request.status
    assert wide_record.outcome.served == minimal_record.outcome.served


# ---------------------------------------------------------------------------
# FAIL CLOSED ON PII -- the packet's most important behaviour
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("column", "value", "category"),
    [
        ("rider_name", "Jordan Ellery", "personal name"),
        ("Client Name", "Jordan Ellery", "personal name"),
        ("full_name", "Jordan Ellery", "personal name"),
        ("name", "Jordan Ellery", "personal name"),
        ("driver_name", "Sam Okafor", "personal name"),
        ("email", "j.ellery@example.org", "email address"),
        ("RiderEmail", "j.ellery@example.org", "email address"),
        ("phone", "555-0100", "phone number"),
        ("Home Phone", "555-0100", "phone number"),
        ("mobile", "555-0100", "phone number"),
        ("pickup_address", "48 Willow Bank Road", "street address"),
        ("street", "Willow Bank Road", "street address"),
        ("addr1", "48 Willow Bank Road", "street address"),
        ("ssn", "000-00-0000", "national, insurance or medical identifier"),
        ("medicaid_id", "MA000000", "national, insurance or medical identifier"),
        ("nhs_number", "000 000 0000", "national, insurance or medical identifier"),
        ("insurance_id", "INS-0", "national, insurance or medical identifier"),
        ("date_of_birth", "1950-01-01", "date of birth"),
        ("dob", "1950-01-01", "date of birth"),
        ("diagnosis", "n/a", "medical or eligibility detail"),
        ("disability_type", "n/a", "medical or eligibility detail"),
        ("eligibility_category", "ADA", "medical or eligibility detail"),
    ],
)
def test_direct_identifier_column_quarantines_the_row_naming_the_field(
    column: str, value: str, category: str
) -> None:
    """SYNTHETIC PII. The row is otherwise perfectly valid -- it must still be
    rejected, and the reason must name the offending column and its category so
    the operator knows exactly what to strip."""

    adapter, _ = minimal_adapter()

    result = adapter.parse(minimal_row(**{column: value}))

    assert result.is_quarantined
    assert result.record is None
    assert result.semantic_loss == ()
    assert isinstance(result.quarantine, QuarantinedRow)
    assert column in result.quarantine.reason
    assert category in result.quarantine.reason
    assert result.quarantine.failed_field == column


def test_pii_value_is_redacted_out_of_the_quarantine_record() -> None:
    """Quarantining is not enough: the rejected value must not be copied into
    the quarantine record either, or the sink the caller writes quarantines to
    becomes the leak."""

    adapter, _ = minimal_adapter()

    result = adapter.parse(minimal_row(rider_name="Jordan Ellery"))

    quarantined = result.quarantine.raw_row
    assert quarantined["rider_name"] == REDACTION_MARKER
    assert "Jordan Ellery" not in str(quarantined)
    assert "Jordan Ellery" not in result.quarantine.reason
    # every non-offending column is still preserved verbatim so the row can be
    # fixed upstream and re-run
    assert quarantined["trip_ref"] == "T-0001"
    assert quarantined["pickup_zone"] == "NW3"


def test_pii_column_quarantines_even_when_blank_in_this_row() -> None:
    """A blank name column in the sample would otherwise hide a populated one in
    the full extract: it is the export SHAPE that carries PII, so the column's
    presence is what fails."""

    adapter, _ = minimal_adapter()

    result = adapter.parse(minimal_row(rider_name=""))

    assert result.is_quarantined
    assert "rider_name" in result.quarantine.reason


def test_pii_rejection_beats_every_other_defect_in_the_row() -> None:
    """A row that is both PII-bearing and otherwise broken must be reported as a
    PII rejection -- the operator has to fix that first."""

    adapter, _ = minimal_adapter()

    result = adapter.parse(minimal_row(rider_name="Jordan Ellery", outcome="", trip_ref=""))

    assert result.is_quarantined
    assert "rider_name" in result.quarantine.reason
    assert "personal name" in result.quarantine.reason


def test_multiple_pii_columns_are_all_named() -> None:
    adapter, _ = minimal_adapter()

    result = adapter.parse(
        minimal_row(rider_name="Jordan Ellery", phone="555-0100", home_address="48 Willow Bank Road")
    )

    reason = result.quarantine.reason
    for column in ("rider_name", "phone", "home_address"):
        assert column in reason
        assert result.quarantine.raw_row[column] == REDACTION_MARKER


def test_email_in_a_renamed_column_is_still_caught() -> None:
    """Renaming `email` to something innocuous must not defeat the check: the
    value is scanned too."""

    adapter, _ = minimal_adapter()

    result = adapter.parse(minimal_row(contact_1="j.ellery@example.org"))

    assert result.is_quarantined
    assert "contact_1" in result.quarantine.reason
    assert "email address" in result.quarantine.reason
    assert "j.ellery@example.org" not in str(result.quarantine.raw_row)


def test_pii_column_is_caught_even_when_the_column_map_points_at_it() -> None:
    """An operator mapping their name column onto rider_ref must not launder it
    through the mapping."""

    tenant_id = new_id(TenantId)
    adapter = OperatorExportAdapter(
        tenant_id, recorded_at=RECORDED_AT, column_map={"rider_name": "rider_ref"}
    )

    result = adapter.parse(minimal_row(rider_name="Jordan Ellery"))

    assert result.is_quarantined
    assert "rider_name" in result.quarantine.reason
    assert result.quarantine.raw_row["rider_name"] == REDACTION_MARKER


def test_street_address_piped_into_a_zone_column_is_quarantined() -> None:
    """The classic accident: the address column is exported into the zone
    column. Zones are the point -- a street address is a rider's home."""

    adapter, _ = minimal_adapter()

    result = adapter.parse(minimal_row(pickup_zone="48 Willow Bank Road"))

    assert result.is_quarantined
    assert "pickup_zone" in result.quarantine.reason
    assert "street address" in result.quarantine.reason
    assert result.quarantine.raw_row["pickup_zone"] == REDACTION_MARKER


def test_address_shaped_dropoff_zone_is_quarantined_through_the_column_map() -> None:
    adapter, _ = wide_vendor_adapter()

    result = adapter.parse(wide_vendor_row(**{"DO Zone": "1600 Cedar Ave"}))

    assert result.is_quarantined
    assert "DO Zone" in result.quarantine.reason  # the operator's own column name
    assert result.quarantine.raw_row["DO Zone"] == REDACTION_MARKER


@pytest.mark.parametrize(
    "column",
    ["route_name", "zone_name", "stop_name", "vehicle_name", "agency_name", "first_stop_name"],
)
def test_ordinary_transit_columns_containing_name_are_not_false_positives(column: str) -> None:
    """Fail-closed must stay usable: quarantining every column with 'name' in it
    would reject ordinary transit exports and train operators to ignore us."""

    assert classify_pii_column(column) is None
    adapter, _ = minimal_adapter()
    assert not adapter.parse(minimal_row(**{column: "Northwest Feeder"})).is_quarantined


@pytest.mark.parametrize(
    "value",
    ["ZONE-NW-3", "Zone 12", "Downtown", "NW3", "Main Street Corridor", "12 North", "90210"],
)
def test_ordinary_zone_labels_are_not_mistaken_for_addresses(value: str) -> None:
    assert looks_like_street_address(value) is False


@pytest.mark.parametrize(
    "value", ["48 Willow Bank Road", "123 Main St", "1600 Cedar Ave", "7 Oak Lane Apt 3"]
)
def test_address_shaped_values_are_detected(value: str) -> None:
    assert looks_like_street_address(value) is True


# ---------------------------------------------------------------------------
# Quarantine, never guess: times, outcomes, required fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("column", list(REQUIRED_COLUMNS))
def test_missing_required_field_is_quarantined_not_defaulted(column: str) -> None:
    adapter, _ = minimal_adapter()

    result = adapter.parse(minimal_row(**{column: ""}))

    assert result.is_quarantined
    assert result.record is None
    assert column in result.quarantine.reason
    assert result.quarantine.failed_field == column


def test_missing_required_field_names_the_operators_own_column() -> None:
    adapter, _ = wide_vendor_adapter()

    result = adapter.parse(wide_vendor_row(PromisedPickup=""))

    assert result.is_quarantined
    assert "scheduled_pickup_at" in result.quarantine.reason
    assert "PromisedPickup" in result.quarantine.reason
    assert result.quarantine.failed_field == "PromisedPickup"


def test_row_with_neither_vehicle_nor_run_ref_is_quarantined() -> None:
    """Deadhead is measured by chaining a vehicle's consecutive trips, so a trip
    naming neither cannot be torn down."""

    adapter, _ = minimal_adapter()

    result = adapter.parse(minimal_row(run_ref=""))

    assert result.is_quarantined
    assert "vehicle_ref" in result.quarantine.reason
    assert "run_ref" in result.quarantine.reason


def test_either_vehicle_or_run_ref_alone_is_enough() -> None:
    adapter, _ = minimal_adapter()

    by_run = adapter.parse(minimal_row(run_ref="RUN-A"))
    by_vehicle = adapter.parse(minimal_row(run_ref="", vehicle_ref="UNIT-412"))

    assert not by_run.is_quarantined
    assert not by_vehicle.is_quarantined
    assert by_vehicle.record.vehicle_ref == "UNIT-412"


@pytest.mark.parametrize(
    "column", ["requested_at", "scheduled_pickup_at", "actual_pickup_at"]
)
@pytest.mark.parametrize("bad", ["not-a-timestamp", "04/03/2026 8:15am", "yesterday", 1772616900])
def test_malformed_timestamp_is_quarantined(column: str, bad: object) -> None:
    adapter, _ = minimal_adapter()

    result = adapter.parse(minimal_row(**{column: bad}))

    assert result.is_quarantined
    assert result.record is None
    assert column in result.quarantine.reason
    assert result.quarantine.failed_field == column


@pytest.mark.parametrize("bad", ["finished", "SERVED?", "status_7", "unknown", "no show pending"])
def test_unknown_outcome_value_is_quarantined_not_bucketed(bad: str) -> None:
    adapter, _ = minimal_adapter()

    result = adapter.parse(minimal_row(outcome=bad))

    assert result.is_quarantined
    assert result.record is None
    assert bad in result.quarantine.reason
    assert "outcome" in result.quarantine.reason
    assert result.quarantine.failed_field == "outcome"


@pytest.mark.parametrize(
    ("raw", "canonical", "state", "served"),
    [
        ("served", "served", ServiceRequestState.COMPLETED, True),
        ("Completed", "served", ServiceRequestState.COMPLETED, True),
        ("no_show", "no_show", ServiceRequestState.NO_SHOW, False),
        ("No Show", "no_show", ServiceRequestState.NO_SHOW, False),
        ("denied", "denied", ServiceRequestState.DENIED, False),
        ("Refused", "denied", ServiceRequestState.DENIED, False),
        ("cancelled", "cancelled", ServiceRequestState.CANCELLED, False),
        ("Canceled", "cancelled", ServiceRequestState.CANCELLED, False),
    ],
)
def test_outcome_vocabulary_maps_to_terminal_state_and_outcome_flag(
    raw: str, canonical: str, state: ServiceRequestState, served: bool
) -> None:
    adapter, _ = minimal_adapter()

    row = minimal_row(outcome=raw)
    if not served:
        row["actual_pickup_at"] = ""
    result = adapter.parse(row)

    assert not result.is_quarantined
    assert result.record.request.status == state
    assert result.record.outcome.served is served

    losses = {loss.source_field: loss for loss in result.semantic_loss}
    if raw != canonical:
        assert losses["outcome"].disposition == "coerced"
        assert losses["outcome"].source_value == raw
    else:
        assert "outcome" not in losses


def test_served_trip_without_an_actual_pickup_time_is_quarantined() -> None:
    """The scheduled time must never be substituted for the actual one."""

    adapter, _ = minimal_adapter()

    result = adapter.parse(minimal_row(actual_pickup_at=""))

    assert result.is_quarantined
    assert "actual_pickup_at" in result.quarantine.reason
    assert "served" in result.quarantine.reason


def test_unserved_trip_may_omit_the_actual_pickup_time() -> None:
    adapter, _ = minimal_adapter()

    result = adapter.parse(minimal_row(outcome="no_show", actual_pickup_at=""))

    assert not result.is_quarantined
    assert result.record.outcome.actual_pickup_at is None
    assert result.record.request.times.actual_pickup_at is None


def test_actual_pickup_on_an_unserved_trip_is_recorded_as_loss_not_mapped() -> None:
    """A trip that was not served has no pickup; the supplied value is recorded
    rather than mapped onto a canonical pickup time or silently dropped."""

    adapter, _ = minimal_adapter()

    result = adapter.parse(minimal_row(outcome="cancelled"))

    assert not result.is_quarantined
    assert result.record.outcome.actual_pickup_at is None
    assert result.record.outcome.served is False
    losses = {loss.source_field: loss for loss in result.semantic_loss}
    assert losses["actual_pickup_at"].disposition == "dropped"


@pytest.mark.parametrize("column", ["scheduled_pickup_at", "actual_pickup_at"])
def test_pickup_time_before_the_request_time_is_quarantined(column: str) -> None:
    adapter, _ = minimal_adapter()

    result = adapter.parse(minimal_row(**{column: "2026-03-01T00:00:00"}))

    assert result.is_quarantined
    assert "before requested_at" in result.quarantine.reason
    assert result.quarantine.failed_field == column


def test_two_source_columns_resolving_to_one_canonical_column_is_quarantined() -> None:
    tenant_id = new_id(TenantId)
    adapter = OperatorExportAdapter(
        tenant_id, recorded_at=RECORDED_AT, column_map={"zone_from": "pickup_zone"}
    )

    result = adapter.parse(minimal_row(zone_from="NW3"))

    assert result.is_quarantined
    assert "pickup_zone" in result.quarantine.reason
    assert "will not choose" in result.quarantine.reason


def test_column_map_targeting_an_unknown_canonical_column_is_a_construction_error() -> None:
    with pytest.raises(ValueError, match="not canonical intake columns"):
        OperatorExportAdapter(
            new_id(TenantId), recorded_at=RECORDED_AT, column_map={"Whatever": "rider_home_address"}
        )


def test_column_map_with_duplicate_targets_is_a_construction_error() -> None:
    with pytest.raises(ValueError, match="more than one source column"):
        OperatorExportAdapter(
            new_id(TenantId),
            recorded_at=RECORDED_AT,
            column_map={"A": "pickup_zone", "B": "pickup_zone"},
        )


# ---------------------------------------------------------------------------
# Rider identity is tokenised, never stored raw
# ---------------------------------------------------------------------------


def test_rider_ref_is_hashed_and_the_raw_value_never_appears_anywhere() -> None:
    adapter, _ = wide_vendor_adapter()

    result = adapter.parse(wide_vendor_row(ClientKey="CL-88213"))

    record = result.record
    assert record.request.rider_ref.startswith("riderref-")
    assert "CL-88213" not in record.request.rider_ref
    assert "CL-88213" not in str(record.model_dump(mode="json"))
    # ...and not smuggled into the semantic-loss record either
    losses = {loss.source_field: loss for loss in result.semantic_loss}
    assert losses["ClientKey"].disposition == "coerced"
    assert losses["ClientKey"].source_value is None
    assert "CL-88213" not in str([loss.model_dump() for loss in result.semantic_loss])


def test_rider_tokenisation_is_deterministic_within_a_tenant() -> None:
    adapter, _ = wide_vendor_adapter()

    first = adapter.parse(wide_vendor_row(BookingNo="BK-1")).record
    second = adapter.parse(wide_vendor_row(BookingNo="BK-2")).record
    other = adapter.parse(wide_vendor_row(BookingNo="BK-3", ClientKey="CL-99999")).record

    assert first.request.rider_ref == second.request.rider_ref
    assert first.request.rider_ref != other.request.rider_ref


def test_absent_rider_column_yields_a_non_joinable_placeholder() -> None:
    """The state the intake document asks for: no rider column at all. The
    placeholder must not link a rider's trips to each other."""

    adapter, _ = minimal_adapter()

    first = adapter.parse(minimal_row(trip_ref="T-1"))
    second = adapter.parse(minimal_row(trip_ref="T-2"))

    assert first.record.request.rider_ref.startswith("operator-no-rider-")
    assert first.record.request.rider_ref != second.record.request.rider_ref

    losses = {loss.source_field: loss for loss in first.semantic_loss}
    assert losses["<no rider identifier column>"].disposition == "dropped"


# ---------------------------------------------------------------------------
# Semantic loss: nothing is silently dropped (ADR-0007)
# ---------------------------------------------------------------------------


def test_every_unmapped_vendor_column_is_reported_as_an_unmapped_extension() -> None:
    adapter, _ = wide_vendor_adapter()

    result = adapter.parse(wide_vendor_row())

    assert not result.is_quarantined
    extensions = {
        loss.source_field for loss in result.semantic_loss if loss.disposition == "unmapped_extension"
    }
    assert extensions == {
        "FareType",
        "ProviderCode",
        "route_name",
        "TripMiles",
        "SchedulingSystem",
        "ExportBatch",
        "OnTimeFlagVendor",
        "Notes",
    }


def test_unmapped_extension_values_are_never_retained() -> None:
    """An unrecognised column is exactly where unanticipated personal data would
    hide, so its name is recorded and its value is not."""

    adapter, _ = wide_vendor_adapter()

    result = adapter.parse(wide_vendor_row(Notes="left at side door"))

    extensions = [
        loss for loss in result.semantic_loss if loss.disposition == "unmapped_extension"
    ]
    assert extensions
    assert all(loss.source_value is None for loss in extensions)
    assert "left at side door" not in str([loss.model_dump() for loss in result.semantic_loss])


def test_a_minimal_export_reports_no_unmapped_extensions() -> None:
    adapter, _ = minimal_adapter()

    result = adapter.parse(minimal_row())

    assert [loss for loss in result.semantic_loss if loss.disposition == "unmapped_extension"] == []


def test_structural_gaps_are_recorded_on_every_mapped_row() -> None:
    """The honest-limitation entries: no lifecycle history, no on-time
    determination, no derived ride-time/deadhead, and no canonical home for the
    vehicle/run reference."""

    adapter, _ = minimal_adapter()

    losses = {loss.source_field: loss for loss in adapter.parse(minimal_row()).semantic_loss}

    assert losses["<lifecycle transitions between request and outcome>"].disposition == "coerced"
    assert losses["<on-time determination>"].disposition == "dropped"
    assert losses["<excess ride time and deadhead>"].disposition == "dropped"
    assert losses["run_ref"].disposition == "dropped"
    assert "no home for a vehicle/run assignment" in losses["run_ref"].reason


def test_naive_timestamps_are_recorded_as_a_coerced_utc_assumption() -> None:
    """The minimal fixture's timestamps carry no offset; the wide one's do."""

    minimal, _ = minimal_adapter()
    wide, _ = wide_vendor_adapter()

    minimal_losses = {loss.source_field: loss for loss in minimal.parse(minimal_row()).semantic_loss}
    naive_entry = minimal_losses["requested_at, scheduled_pickup_at, actual_pickup_at"]
    assert naive_entry.disposition == "coerced"
    assert "no UTC offset" in naive_entry.reason

    # the wide fixture carries explicit -05:00 offsets, so no such coercion exists
    wide_reasons = [loss.reason for loss in wide.parse(wide_vendor_row()).semantic_loss]
    assert not any("no UTC offset" in reason for reason in wide_reasons)


def test_no_semantic_loss_is_attached_to_a_quarantined_row() -> None:
    """AdapterResult enforces exactly-one-outcome; assert it holds for this
    adapter's quarantine paths too."""

    adapter, _ = minimal_adapter()

    for row in (
        minimal_row(rider_name="Jordan Ellery"),
        minimal_row(outcome="finished"),
        minimal_row(requested_at="nope"),
        minimal_row(trip_ref=""),
    ):
        result = adapter.parse(row)
        assert result.is_quarantined
        assert result.record is None
        assert result.semantic_loss == ()


# ---------------------------------------------------------------------------
# Batch behaviour
# ---------------------------------------------------------------------------


def test_one_pii_row_does_not_stop_the_rest_of_the_batch() -> None:
    adapter, _ = minimal_adapter()
    rows = [
        minimal_row(trip_ref="T-1"),
        minimal_row(trip_ref="T-2", rider_name="Jordan Ellery"),
        minimal_row(trip_ref="T-3", outcome="finished"),
        minimal_row(trip_ref="T-4"),
    ]

    results = parse_batch(adapter, rows)

    assert [result.is_quarantined for result in results] == [False, True, True, False]
    assert "personal name" in results[1].quarantine.reason
    assert "unknown outcome" in results[2].quarantine.reason
    assert results[0].record.request.request_id != results[3].record.request.request_id


def test_a_wide_and_a_minimal_batch_both_survive_parse_batch() -> None:
    wide, _ = wide_vendor_adapter()
    minimal, _ = minimal_adapter()

    wide_results = parse_batch(wide, [wide_vendor_row(BookingNo=f"BK-{i}") for i in range(5)])
    minimal_results = parse_batch(minimal, [minimal_row(trip_ref=f"T-{i}") for i in range(5)])

    assert all(not result.is_quarantined for result in wide_results)
    assert all(not result.is_quarantined for result in minimal_results)
    assert len({result.record.request.request_id for result in wide_results}) == 5


# ---------------------------------------------------------------------------
# The document an agency actually reads must not drift from the code
# ---------------------------------------------------------------------------


def test_intake_document_publishes_the_field_list_the_adapter_enforces() -> None:
    text = INTAKE_DOC.read_text(encoding="utf-8")

    for column in CANONICAL_COLUMNS:
        assert f"`{column}`" in text, f"{column} is enforced in code but not published in the doc"
    for value in OUTCOME_VALUES:
        assert f"`{value}`" in text


def test_intake_document_states_what_the_packet_requires_it_to_state() -> None:
    """The six things `MX-C-OPERATOR-INTAKE-003.the_document_must_state` names,
    plus the upstream blocker it must flag."""

    text = INTAKE_DOC.read_text(encoding="utf-8")

    # minimum field list, formats, and a worked column mapping
    assert "minimum field list" in text.lower()
    assert "CSV" in text and "Parquet" in text
    assert "column_map" in text

    # what we do with it: purpose limitation, RLS with FORCE (ADR-0018), no onward sharing
    assert "Purpose limitation" in text
    assert "row-level security" in text.lower()
    assert "FORCE" in text
    assert "0018-postgres-row-level-security" in text
    assert "No onward sharing" in text

    # retention, deletion on request, and how deletion is confirmed
    assert "Retention period" in text
    assert "Deletion on request" in text
    assert "How deletion is confirmed" in text
    assert "SHA-256" in text

    # the blunt section, stated plainly
    assert "WHAT WE DO NOT WANT" in text

    # status honesty -- Demonstrated, not operator-Validated, no implied customers
    assert "no operator customers" in text
    assert "Demonstrated" in text
    assert "Validated" in text

    # the agreement itself is a legal/founder task, not something this repo provides
    assert "not an agreement" in text
    assert "signed by the founders" in text


def test_intake_document_names_every_pii_category_the_adapter_rejects() -> None:
    """An operator can only comply with a rule they were told about."""

    text = INTAKE_DOC.read_text(encoding="utf-8").lower()

    for keyword in (
        "names",
        "email addresses",
        "phone numbers",
        "street addresses",
        "national, insurance or medical identifiers",
        "dates of birth",
        "medical or eligibility detail",
    ):
        assert keyword in text
