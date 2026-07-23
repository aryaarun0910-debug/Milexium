"""Adapter: NYC TLC FHVHV trip parquet (realdata/raw_tlc/) -> ServiceRequest (v0.1).

Status: **Demonstrated** only. NYC TLC For-Hire Vehicle High Volume (FHVHV)
trip records are real, individual, publicly-published trips (every Uber/
Lyft/Via/Juno ride in NYC) -- not fictional generator output like
reference_agency_trips.py's source, but also not consented paratransit
operator data. Nothing here may be promoted to "Validated" on the strength
of this adapter alone, per architecture/decisions/0001.

This is deliberately a *structurally different* second adapter against the
same packages.connect.adapter.SourceAdapter contract, to exercise real
cross-source heterogeneity (blueprint/01, "unavoidable" test #1): the source
is columnar Parquet, not a delimited CSV; raw values arrive as pandas/numpy
native types (Timestamp, int64, NaT, pandas.NA) rather than strings; nulls
are a first-class concept the source itself uses (unlike reference_agency's
empty-string convention); and there is no rider identity of any kind.

FHVHV parquet columns, confirmed directly against
realdata/raw_tlc/fhvhv_tripdata_2019-02.parquet and cross-checked against
realdata/raw_tlc/fhvhv_tripdata_2026-05.parquet (24 columns in 2019-02; the
2026-05 file adds a 25th, `cbd_congestion_fee`, real observed schema drift
from NYC's 2025 congestion-pricing program, not a hypothetical):
    hvfhs_license_num, dispatching_base_num, originating_base_num,
    request_datetime, on_scene_datetime, pickup_datetime, dropoff_datetime,
    PULocationID, DOLocationID, trip_miles, trip_time, base_passenger_fare,
    tolls, bcf, sales_tax, congestion_surcharge, airport_fee, tips,
    driver_pay, shared_request_flag, shared_match_flag, access_a_ride_flag,
    wav_request_flag, wav_match_flag[, cbd_congestion_fee]
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pandas as pd

from packages.canonical import (
    BitemporalMeta,
    RequestId,
    RequestTimes,
    ServiceRequest,
    ServiceRequestState,
    TenantId,
    new_id,
)
from packages.connect.adapter import AdapterResult, QuarantinedRow, SemanticLossRecord

REQUIRED_COLUMNS = ("request_datetime", "PULocationID", "DOLocationID")

_UNKNOWN_ZONE_CODES = frozenset({264, 265})
"""TLC's own placeholder location ids: 264 = unknown/NA, 265 = outside of NYC.
Neither is a real geographic zone. Observed in realdata/raw_tlc/
fhvhv_tripdata_2019-02.parquet: 1,292 pickups and 601,365 dropoffs (of
20,159,102 rows) carry one of these two codes -- a real, common failure
mode, not a hypothetical one."""

_UNMAPPED_COLUMN_REASONS = {
    "on_scene_datetime": (
        "driver-arrival-on-scene timestamp has no ServiceRequest field distinct from "
        "actual_pickup_at; on-demand dispatch has no scheduling step to hold it"
    ),
    "dropoff_datetime": (
        "ServiceRequest models the request, not the executed trip; no field records a "
        "trip's end/dropoff timestamp"
    ),
    "trip_miles": "trip distance has no ServiceRequest v0.1 field",
    "trip_time": "trip duration has no ServiceRequest v0.1 field",
    "base_passenger_fare": "fare/financial fields have no ServiceRequest v0.1 home",
    "tolls": "fare/financial fields have no ServiceRequest v0.1 home",
    "bcf": "fare/financial fields have no ServiceRequest v0.1 home",
    "sales_tax": "fare/financial fields have no ServiceRequest v0.1 home",
    "congestion_surcharge": "fare/financial fields have no ServiceRequest v0.1 home",
    "airport_fee": "fare/financial fields have no ServiceRequest v0.1 home",
    "tips": "fare/financial fields have no ServiceRequest v0.1 home",
    "driver_pay": "fare/financial fields have no ServiceRequest v0.1 home",
    "shared_request_flag": "carpool/shared-ride request flag has no ServiceRequest v0.1 field",
    "shared_match_flag": "carpool/shared-ride match flag has no ServiceRequest v0.1 field",
    "access_a_ride_flag": (
        "flags a cross-program link to NYC's Access-A-Ride paratransit program; "
        "ServiceRequest v0.1 has no field for a source-program linkage"
    ),
    "wav_match_flag": (
        "whether the vehicle actually dispatched was wheelchair-accessible is an "
        "outcome/vehicle-level fact (see Vehicle.accessibility_equipment or a future "
        "Outcome field), not a ServiceRequest attribute"
    ),
    "hvfhs_license_num": (
        "identifies the operating TNC (Uber/Lyft/Via/Juno); no ServiceRequest v0.1 field "
        "for the source vendor"
    ),
    "dispatching_base_num": (
        "identifies the TLC-licensed dispatching base station, not a rider; no "
        "ServiceRequest v0.1 home"
    ),
    "originating_base_num": (
        "identifies the TLC-licensed originating base station, not a rider; no "
        "ServiceRequest v0.1 home"
    ),
}

_KNOWN_COLUMNS = (
    frozenset(REQUIRED_COLUMNS)
    | frozenset(_UNMAPPED_COLUMN_REASONS)
    | frozenset({"pickup_datetime", "wav_request_flag"})
)


class _UnmappableValue(ValueError):
    """Internal signal that a field value cannot become canonical; caught in
    parse() and turned into a QuarantinedRow rather than propagating."""


def _is_missing(value: object) -> bool:
    """True for None, NaN, NaT, and pandas.NA alike -- the null vocabulary a
    real Parquet/pandas source actually uses, unlike reference_agency's CSV
    convention of a bare empty string."""
    return bool(pd.isna(value))


def _to_utc(value: object) -> datetime:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if not isinstance(value, datetime):
        raise _UnmappableValue(f"unparseable timestamp: {value!r}")
    if value.tzinfo is not None:
        raise _UnmappableValue(
            f"unexpected timezone-aware timestamp {value!r}; FHVHV publishes naive local time only"
        )
    return value.replace(tzinfo=timezone.utc)


def _zone_str(column: str, raw_value: object) -> str:
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise _UnmappableValue(f"unparseable {column} value: {raw_value!r}") from exc
    if value in _UNKNOWN_ZONE_CODES:
        raise _UnmappableValue(
            f"{column}={value} is TLC's own unknown/outside-NYC placeholder zone code "
            "(264/265), not a real geographic zone"
        )
    return str(value)


def _parse_mobility_device(raw_value: object) -> tuple[str | None, bool]:
    """Returns (mobility_device, had_real_signal) so parse() can choose the
    right semantic-loss disposition: coerced when a real Y/N flag existed,
    dropped when the field truly carried no signal for this row."""
    if _is_missing(raw_value) or raw_value == "":
        return None, False
    token = str(raw_value).strip().upper()
    if token == "Y":
        return "wheelchair", True
    if token == "N":
        return None, True
    raise _UnmappableValue(f"unrecognized wav_request_flag value {raw_value!r}")


def _synthetic_rider_ref(raw_row: dict) -> str:
    # FHVHV publishes no rider/passenger identifier at all; this hash is a
    # deterministic per-row placeholder that satisfies ServiceRequest.rider_ref,
    # never a stable or joinable entity id -- unlike reference_agency_trips.py's
    # tokenized rider_id, which does persist across one fictional rider's trips.
    basis = "|".join(
        str(raw_row.get(field)) for field in ("request_datetime", "PULocationID", "DOLocationID", "driver_pay")
    )
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    return f"tlc-no-rider-{digest}"


class TlcTripsAdapter:
    """Maps one NYC TLC FHVHV trip row onto a fresh ServiceRequest.

    `recorded_at` is the adapter run's own transaction time (BitemporalMeta),
    distinct from the trip's valid-time fields -- it is not read from the
    source, which has no notion of import/transaction time at all.
    """

    adapter_name = "tlc-fhvhv-trips-parquet"
    adapter_version = "0.1.0"

    def __init__(self, tenant_id: TenantId, *, recorded_at: datetime) -> None:
        self._tenant_id = tenant_id
        self._recorded_at = recorded_at

    def parse(self, raw_row: dict) -> AdapterResult[ServiceRequest]:
        missing = [c for c in REQUIRED_COLUMNS if _is_missing(raw_row.get(c))]
        if missing:
            return AdapterResult(
                quarantine=QuarantinedRow(
                    raw_row=dict(raw_row),
                    reason=f"missing required field(s): {', '.join(missing)}",
                    failed_field=missing[0],
                )
            )

        try:
            requested_at = _to_utc(raw_row["request_datetime"])
            pickup_zone = _zone_str("PULocationID", raw_row["PULocationID"])
            dropoff_zone = _zone_str("DOLocationID", raw_row["DOLocationID"])
            pickup_present = not _is_missing(raw_row.get("pickup_datetime"))
            actual_pickup_at = _to_utc(raw_row["pickup_datetime"]) if pickup_present else None
            mobility_device, wav_present = _parse_mobility_device(raw_row.get("wav_request_flag"))
        except _UnmappableValue as exc:
            return AdapterResult(quarantine=QuarantinedRow(raw_row=dict(raw_row), reason=str(exc)))

        semantic_loss = [
            SemanticLossRecord(
                source_field="request_datetime",
                source_value=str(raw_row["request_datetime"]),
                reason=(
                    "request_datetime is the on-demand app-hail request instant, not an "
                    "advance-notice paratransit booking call -- the closest available concept "
                    "to requested_at, but a different demand pattern (typically minutes, not "
                    "days, before pickup). TLC also publishes it as naive local "
                    "America/New_York time with no declared IANA zone; treated as UTC directly "
                    "without offset conversion, the same simplification reference_agency_trips.py "
                    "and conformance/fixtures/builders.py already use elsewhere in this repo -- "
                    "the true UTC instant differs by 4-5 hours (EDT/EST)"
                ),
                disposition="coerced",
            )
        ]
        if pickup_present:
            semantic_loss.append(
                SemanticLossRecord(
                    source_field="pickup_datetime",
                    source_value=str(raw_row["pickup_datetime"]),
                    reason=(
                        "mapped to actual_pickup_at as the observed trip start; on-demand "
                        "ride-hail dispatch has no advance-scheduling or negotiated-window step "
                        "at all, so negotiated_window_*/scheduled_pickup_at are correctly left "
                        "unset here -- a structural difference from the paratransit domain, not "
                        "a missing signal"
                    ),
                    disposition="coerced",
                )
            )
        semantic_loss.append(
            SemanticLossRecord(
                source_field="wav_request_flag",
                source_value=str(raw_row.get("wav_request_flag")) if wav_present else None,
                reason=(
                    "wav_request_flag is a request for a wheelchair-accessible VEHICLE, not a "
                    "direct report of the rider's own mobility device; mapped to "
                    "mobility_device='wheelchair' on 'Y' as the closest available real signal "
                    "in this source"
                    if wav_present
                    else (
                        "field missing/null for this row -- no accessibility-request signal to "
                        "map; mobility_device left unset rather than guessed"
                    )
                ),
                disposition="coerced" if wav_present else "dropped",
            )
        )
        semantic_loss.append(
            SemanticLossRecord(
                source_field="<no rider/passenger identifier column>",
                source_value=None,
                reason=(
                    "FHVHV publishes zero rider/passenger-level identifier of any kind (by "
                    "design, for rider privacy); hvfhs_license_num/dispatching_base_num/"
                    "originating_base_num identify the TNC and dispatching base station, never "
                    "a person, so tokenizing them the way reference_agency_trips.py tokenizes "
                    "an actual per-rider id would misrepresent millions of unrelated riders as "
                    "one identity; rider_ref is instead a synthetic per-row placeholder, not a "
                    "stable or joinable entity reference"
                ),
                disposition="dropped",
            )
        )
        semantic_loss.append(
            SemanticLossRecord(
                source_field="<implicit trip outcome>",
                source_value=None,
                reason=(
                    "FHVHV publishes only trips that were actually dispatched and completed "
                    "(no cancellation/no-show rows); representing that as "
                    "ServiceRequestState.COMPLETED would require walking the request through "
                    "NEGOTIATED/SCHEDULED/IN_PROGRESS via check_transition, out of scope for a "
                    "one-row parse -- status is left at REQUESTED, the same scope boundary "
                    "reference_agency_trips.py drew for its own 'status' column"
                ),
                disposition="dropped",
            )
        )
        for column, reason in _UNMAPPED_COLUMN_REASONS.items():
            value = raw_row.get(column)
            if not _is_missing(value):
                semantic_loss.append(
                    SemanticLossRecord(
                        source_field=column, source_value=str(value), reason=reason, disposition="dropped"
                    )
                )
        for column, value in raw_row.items():
            if column not in _KNOWN_COLUMNS:
                semantic_loss.append(
                    SemanticLossRecord(
                        source_field=column,
                        source_value=str(value) if not _is_missing(value) else None,
                        reason=(
                            "not part of the FHVHV schema this adapter was written against "
                            "(observed real schema drift -- e.g. cbd_congestion_fee, added 2025+)"
                        ),
                        disposition="unmapped_extension",
                    )
                )

        request = ServiceRequest(
            request_id=new_id(RequestId),
            tenant_id=self._tenant_id,
            rider_ref=_synthetic_rider_ref(raw_row),
            pickup_zone=pickup_zone,
            dropoff_zone=dropoff_zone,
            mobility_device=mobility_device,
            times=RequestTimes(requested_at=requested_at, actual_pickup_at=actual_pickup_at),
            status=ServiceRequestState.REQUESTED,
            meta=BitemporalMeta(version=1, recorded_at=self._recorded_at),
        )
        return AdapterResult(record=request, semantic_loss=tuple(semantic_loss))
