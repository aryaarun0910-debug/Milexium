"""Typed identifiers for the canonical contract (v0.1).

Each identifier is a distinct Pydantic-validated string type so a verifier can
reject "a VehicleId where a DriverId belongs" at the type/schema boundary
rather than relying on every caller to remember which raw string means what.
Values are UUIDv7 (time-ordered, per RFC 9562) formatted as lowercase
canonical UUID strings.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import AfterValidator, GetCoreSchemaHandler
from pydantic_core import core_schema

_UUID_VERSION = 7


def _validate_uuid_string(value: str) -> str:
    parsed = uuid.UUID(value)
    if parsed.version != _UUID_VERSION:
        raise ValueError(
            f"expected a UUIDv{_UUID_VERSION} string, got version {parsed.version}: {value!r}"
        )
    return str(parsed)


class _TypedId(str):
    """Base for a distinct, validated identifier kind.

    Subclasses exist only to be distinct types for Pydantic/typing purposes;
    they do not add behavior beyond UUIDv7 validation.
    """

    def __new__(cls, value: str) -> "_TypedId":
        return str.__new__(cls, _validate_uuid_string(value))

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: object, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls, core_schema.str_schema()
        )


class TenantId(_TypedId):
    """Identifies the tenant boundary that must appear on every operational record."""


class RequestId(_TypedId):
    """Identifies a ServiceRequest aggregate (bitemporal: an id spans corrections)."""


class VehicleId(_TypedId):
    pass


class DriverId(_TypedId):
    pass


class PolicyId(_TypedId):
    pass


class ModelVersionId(_TypedId):
    pass


class ScheduleRunId(_TypedId):
    pass


class DecisionEventId(_TypedId):
    pass


class ObservationId(_TypedId):
    """Identifies one request-INDEPENDENT operational observation (vehicle
    telemetry or a stop-time observation).

    This is the record's OWN surrogate key, not a reference to any other
    aggregate. It is the deliberate counterpoint to the synthetic
    ``Outcome.request_id`` ADR-0031 was forced to mint: that id was a *foreign
    key to a ServiceRequest that does not exist* (a dishonest placeholder for
    request-less telemetry); this id is the observation's own primary key and
    points at nothing it cannot back up. See VehicleObservation /
    StopTimeObservation in entities.py.
    """


AggregateId = Annotated[str, AfterValidator(_validate_uuid_string)]
"""An id known only to be *some* aggregate's id (used by the generic event log)."""


def new_id(kind: type[_TypedId]) -> _TypedId:
    """Mint a fresh, time-ordered id of the given typed-id kind."""
    return kind(str(uuid.uuid7()))
