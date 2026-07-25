"""Program A: canonical transport substrate.

Normative contract version: v0.1 (see architecture/contracts/canonical-v0.1.json
and architecture/decisions/0002-canonical-schema-technology.md). Owned by this
package only -- other packages read it, they do not redefine it in place.
"""

from packages.canonical.ids import (
    PLATFORM_TENANT_ID,
    PLATFORM_TENANT_NAME,
    AggregateId,
    BlockId,
    DeadheadSegmentId,
    DecisionEventId,
    DriverId,
    ModelVersionId,
    ObservationId,
    PolicyId,
    RequestId,
    RunPieceId,
    ScheduleRunId,
    TenantId,
    VehicleId,
    new_id,
)
from packages.canonical.time import BitemporalMeta, RequestTimes
from packages.canonical.entities import (
    PLATFORM_TENANT_CREATED_AT,
    Block,
    DeadheadKind,
    DeadheadSegment,
    DecisionAlternative,
    DecisionEvent,
    Driver,
    ForecastVintage,
    ModelVersion,
    Outcome,
    OutboxEntry,
    Policy,
    RunPiece,
    ScheduleRun,
    ServiceRequest,
    StopTimeObservation,
    Tenant,
    Vehicle,
    VehicleObservation,
    platform_tenant,
)
from packages.canonical.state_machine import (
    ILLEGAL_TRANSITIONS_EXAMPLE,
    SERVICE_REQUEST_TRANSITIONS,
    ServiceRequestState,
    TransitionError,
    check_transition,
)
from packages.canonical.vocab import (
    DecisionEventType,
    ReasonCode,
    ScheduleRunStatus,
    SensitivityClass,
)
from packages.canonical.events import HashChainAppender
from packages.canonical.storage import SqliteCanonicalStore

__all__ = [
    "AggregateId",
    "BlockId",
    "DeadheadSegmentId",
    "DecisionEventId",
    "DriverId",
    "ModelVersionId",
    "ObservationId",
    "PolicyId",
    "RequestId",
    "RunPieceId",
    "ScheduleRunId",
    "TenantId",
    "VehicleId",
    "new_id",
    "PLATFORM_TENANT_ID",
    "PLATFORM_TENANT_NAME",
    "PLATFORM_TENANT_CREATED_AT",
    "platform_tenant",
    "RequestTimes",
    "BitemporalMeta",
    "Block",
    "DeadheadKind",
    "DeadheadSegment",
    "DecisionAlternative",
    "DecisionEvent",
    "Driver",
    "ForecastVintage",
    "ModelVersion",
    "Outcome",
    "Policy",
    "RunPiece",
    "ScheduleRun",
    "ServiceRequest",
    "StopTimeObservation",
    "Tenant",
    "Vehicle",
    "VehicleObservation",
    "OutboxEntry",
    "ILLEGAL_TRANSITIONS_EXAMPLE",
    "SERVICE_REQUEST_TRANSITIONS",
    "ServiceRequestState",
    "TransitionError",
    "check_transition",
    "DecisionEventType",
    "ReasonCode",
    "ScheduleRunStatus",
    "SensitivityClass",
    "HashChainAppender",
    "SqliteCanonicalStore",
]

CONTRACT_VERSION = "0.1.0"
