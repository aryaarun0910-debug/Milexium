"""Adapter: reference_agency/output/trips.csv -> ServiceRequest (v0.1).

Status: **Demonstrated** only (reference_agency/generate_trips.py fabricates
"Harland County Mobility" -- no real rider ever existed). Nothing here may be
promoted to "Validated" without consented operator data against a declared
baseline, per architecture/decisions/0001.

trips.csv columns (from generate_trips.py):
    date, hour, rider_id, origin_zone, dest_zone, purpose, wheelchair,
    subscription, req_minute, status
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

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

REQUIRED_COLUMNS = ("date", "hour", "req_minute", "rider_id", "origin_zone", "dest_zone")

_KNOWN_COLUMNS = frozenset(REQUIRED_COLUMNS) | frozenset({"purpose", "wheelchair", "subscription", "status"})

_UNMAPPED_COLUMN_REASONS = {
    "purpose": "ServiceRequest v0.1 has no trip-purpose field",
    "subscription": "ServiceRequest v0.1 has no standing-order/subscription flag",
    "status": (
        "source trip outcome (completed/cancelled/no_show) has no home on "
        "ServiceRequest; representing it requires an Outcome record and/or a "
        "state-machine transition, out of scope for this adapter"
    ),
}

_TRUE_TOKENS = frozenset({"true", "1", "yes"})
_FALSE_TOKENS = frozenset({"false", "0", "no"})


class _UnmappableValue(ValueError):
    """Internal signal that a field value cannot become canonical; caught in
    parse() and turned into a QuarantinedRow rather than propagating."""


def _parse_requested_at(raw_row: dict) -> datetime:
    try:
        day = datetime.strptime(raw_row["date"], "%Y-%m-%d")
        hour = int(raw_row["hour"])
        minute = int(raw_row["req_minute"])
    except (KeyError, ValueError) as exc:
        raise _UnmappableValue(f"unparseable pickup time components: {exc}") from exc
    if not (0 <= hour <= 23) or not (0 <= minute <= 59):
        raise _UnmappableValue(
            f"pickup time out of range: hour={raw_row['hour']!r} req_minute={raw_row['req_minute']!r}"
        )
    return (day + timedelta(hours=hour, minutes=minute)).replace(tzinfo=timezone.utc)


def _parse_mobility_device(raw_value: str | None) -> str | None:
    if raw_value is None or raw_value == "":
        return None
    token = raw_value.strip().lower()
    if token in _TRUE_TOKENS:
        return "wheelchair"
    if token in _FALSE_TOKENS:
        return None
    raise _UnmappableValue(f"unrecognized wheelchair value {raw_value!r}")


def _tokenize_rider(rider_id: str) -> str:
    # sha256 rather than passing rider_id through: this source's id is not a
    # name, but the adapter must not assume that of every future source.
    digest = hashlib.sha256(rider_id.encode("utf-8")).hexdigest()[:24]
    return f"riderref-{digest}"


class ReferenceAgencyTripsAdapter:
    """Maps one reference_agency trips.csv row onto a fresh ServiceRequest.

    `recorded_at` is the adapter run's own transaction time (BitemporalMeta),
    distinct from the trip's valid-time fields -- it is not read from the
    source, which has no notion of import/transaction time at all.
    """

    adapter_name = "reference-agency-trips-csv"
    adapter_version = "0.1.0"

    def __init__(self, tenant_id: TenantId, *, recorded_at: datetime) -> None:
        self._tenant_id = tenant_id
        self._recorded_at = recorded_at

    def parse(self, raw_row: dict) -> AdapterResult[ServiceRequest]:
        missing = [c for c in REQUIRED_COLUMNS if not raw_row.get(c)]
        if missing:
            return AdapterResult(
                quarantine=QuarantinedRow(
                    raw_row=dict(raw_row),
                    reason=f"missing required field(s): {', '.join(missing)}",
                    failed_field=missing[0],
                )
            )

        try:
            requested_at = _parse_requested_at(raw_row)
            mobility_device = _parse_mobility_device(raw_row.get("wheelchair"))
        except _UnmappableValue as exc:
            return AdapterResult(quarantine=QuarantinedRow(raw_row=dict(raw_row), reason=str(exc)))

        semantic_loss = [
            SemanticLossRecord(
                source_field="date/hour/req_minute",
                source_value=f"{raw_row['date']} {raw_row['hour']}:{raw_row['req_minute']}",
                reason=(
                    "source records one trip timestamp and does not distinguish "
                    "call/request time from negotiated or scheduled pickup time; "
                    "mapped to requested_at only -- negotiated_window_* and "
                    "scheduled_pickup_at are left unset rather than guessed"
                ),
                disposition="coerced",
            )
        ]
        for column, reason in _UNMAPPED_COLUMN_REASONS.items():
            value = raw_row.get(column)
            if value not in (None, ""):
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
                        source_value=str(value) if value is not None else None,
                        reason="not part of the documented reference_agency trips.csv schema",
                        disposition="unmapped_extension",
                    )
                )

        request = ServiceRequest(
            request_id=new_id(RequestId),
            tenant_id=self._tenant_id,
            rider_ref=_tokenize_rider(raw_row["rider_id"]),
            pickup_zone=raw_row["origin_zone"],
            dropoff_zone=raw_row["dest_zone"],
            mobility_device=mobility_device,
            times=RequestTimes(requested_at=requested_at),
            status=ServiceRequestState.REQUESTED,
            meta=BitemporalMeta(version=1, recorded_at=self._recorded_at),
        )
        return AdapterResult(record=request, semantic_loss=tuple(semantic_loss))
