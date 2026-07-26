"""Program B: Milexium Connect (first slice).

Not wired into the top-level app/__init__.py or pyproject.toml by this
change -- see this packet's final report for why (owned-path boundary with
parallel work). Import directly: `from app.connect import ...`.
"""

from app.connect.adapter import (
    AdapterResult,
    QuarantinedRow,
    SemanticLossRecord,
    SourceAdapter,
    parse_batch,
)
from app.connect.reference_agency_trips import ReferenceAgencyTripsAdapter
from app.connect.tlc_trips import (
    NO_VEHICLE_REFERENCE_FIELD as TLC_NO_VEHICLE_REFERENCE_FIELD,
)
from app.connect.tlc_trips import (
    PERSON_IDENTIFYING_COLUMNS,
    TlcTripsAdapter,
    person_identifying_category,
)
from app.connect.tides_trips import TidesPerformedTrip, TidesTripsAdapter
from app.connect.gtfs_flex import (
    NO_VEHICLE_REFERENCE_FIELD as GTFS_FLEX_NO_VEHICLE_REFERENCE_FIELD,
)
from app.connect.gtfs_flex import GtfsFlexAdapter
from app.connect.gtfs_realtime import (
    NO_RUN_REFERENCE_FIELD as GTFS_REALTIME_NO_RUN_REFERENCE_FIELD,
)
from app.connect.gtfs_realtime import (
    GtfsRealtimeAdapter,
    feed_message_to_rows,
    read_gtfs_realtime_feed,
)
from app.connect.operator_export import (
    REPAIR_RULES,
    OperatorExportAdapter,
    OperatorTripRecord,
    coerce_boolean_like,
    repair_rule_of,
    resolve_intake_columns,
)
from app.connect.ingest_report import (
    IngestQualityReport,
    MissingnessDiagnosis,
    build_ingest_report,
    classify_quarantine_reason,
)

__all__ = [
    "AdapterResult",
    "QuarantinedRow",
    "SemanticLossRecord",
    "SourceAdapter",
    "parse_batch",
    "ReferenceAgencyTripsAdapter",
    "TlcTripsAdapter",
    "TidesTripsAdapter",
    "TidesPerformedTrip",
    "GtfsFlexAdapter",
    "GtfsRealtimeAdapter",
    # MX-B-ADAPTER-REFS-009: the per-format record of which vehicle/run
    # reference each source actually carries -- including the ones that carry
    # none, which is a finding rather than a placeholder.
    "GTFS_FLEX_NO_VEHICLE_REFERENCE_FIELD",
    "GTFS_REALTIME_NO_RUN_REFERENCE_FIELD",
    "TLC_NO_VEHICLE_REFERENCE_FIELD",
    "PERSON_IDENTIFYING_COLUMNS",
    "person_identifying_category",
    "feed_message_to_rows",
    "read_gtfs_realtime_feed",
    "OperatorExportAdapter",
    "OperatorTripRecord",
    "REPAIR_RULES",
    "coerce_boolean_like",
    "repair_rule_of",
    "resolve_intake_columns",
    "IngestQualityReport",
    "MissingnessDiagnosis",
    "build_ingest_report",
    "classify_quarantine_reason",
]

CONTRACT_VERSION = "0.1.0"
