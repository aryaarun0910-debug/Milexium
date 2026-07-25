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


class BlockId(_TypedId):
    """Identifies one `Block` -- a vehicle's continuous work between pull-out and
    pull-in. The record's OWN surrogate key (see the note below on why the
    scheduling family gets three distinct id kinds rather than one shared one)."""


class RunPieceId(_TypedId):
    """Identifies one `RunPiece` -- one continuous piece of an operator's run."""


class DeadheadSegmentId(_TypedId):
    """Identifies one `DeadheadSegment` -- one non-revenue vehicle movement.

    WHY THE SCHEDULING FAMILY HAS THREE ID KINDS AND THE TELEMETRY FAMILY HAS
    ONE. ``ObservationId`` above is deliberately shared by ``VehicleObservation``
    and ``StopTimeObservation`` because neither entity references the other, so a
    single opaque "this record's own key" type can never be mixed up in practice.
    The scheduling family DOES reference itself: a ``RunPiece`` and a
    ``DeadheadSegment`` each carry the ``BlockId`` of the block they belong to.
    With one shared type, passing a deadhead segment's id where a block id
    belongs would type-check and insert a dangling reference -- exactly the
    "a VehicleId where a DriverId belongs" error this module exists to reject.
    Three types make that a validation failure at the boundary instead.
    """


AggregateId = Annotated[str, AfterValidator(_validate_uuid_string)]
"""An id known only to be *some* aggregate's id (used by the generic event log)."""


PLATFORM_TENANT_ID = TenantId("00000000-0000-7000-8000-000000000000")
"""The one reserved tenant that owns records belonging to no customer.

ADR-0040. `ModelVersion.tenant_id` is mandatory, but the models trained in this
repository are trained on *public* data (NYC TLC, Chicago TNP, MTA, NTD) and
belong to no customer. ADR-0040 rejected making `tenant_id` nullable for that
case -- `tenant_id = current_setting(...)` is never true for NULL, so nullable
rows would be invisible under the existing RLS policy and every consumer would
need a special case, the first forgotten one returning a silently wrong answer
instead of an error. A reserved id keeps the "every operational record carries a
tenant" invariant intact.

WHY THIS EXACT VALUE. It is a syntactically valid UUIDv7 (version nibble 7,
RFC-4122 variant), so it satisfies the same validation as every other TenantId
and needs no exemption anywhere -- but it is all-zeros otherwise, so it can never
collide with a minted `new_id(TenantId)` (whose leading 48 bits are a
millisecond timestamp, never zero) and is recognisable on sight in a table dump.
It is a WELL-KNOWN CONSTANT: changing it orphans every row already stamped with
it, so `conformance/property-tests/test_platform_tenant.py` pins the literal.

THE TWO THINGS THAT MAKE IT REAL, both required (ADR-0040: a constant without
them "looks finished" and is worse than an honest placeholder):
1. It exists as an actual row in `tenants` -- the foreign key from every
   tenant-scoped table demands it. Both stores seed it idempotently at setup.
2. `sql/rls_postgres.sql` gives `model_versions` an ASYMMETRIC policy: the
   USING clause admits `tenant_id = <this constant>` so any tenant may READ a
   platform model, while the WITH CHECK clause omits it, so a session acting as
   a tenant cannot WRITE a platform-stamped row. A customer can use a platform
   model and cannot forge one.
"""

PLATFORM_TENANT_NAME = "Milexium platform (reserved)"
"""The reserved tenant's `name`. Says "reserved" out loud so the row is never
mistaken for a customer registration in a table dump."""


def new_id(kind: type[_TypedId]) -> _TypedId:
    """Mint a fresh, time-ordered id of the given typed-id kind."""
    return kind(str(uuid.uuid7()))
