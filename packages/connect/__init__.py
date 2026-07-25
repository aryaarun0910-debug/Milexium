"""Program B: Milexium Connect (first slice).

Not wired into the top-level packages/__init__.py or pyproject.toml by this
change -- see this packet's final report for why (owned-path boundary with
parallel work). Import directly: `from packages.connect import ...`.
"""

from packages.connect.adapter import (
    AdapterResult,
    QuarantinedRow,
    SemanticLossRecord,
    SourceAdapter,
    parse_batch,
)
from packages.connect.reference_agency_trips import ReferenceAgencyTripsAdapter
from packages.connect.tlc_trips import TlcTripsAdapter
from packages.connect.tides_trips import TidesTripsAdapter
from packages.connect.gtfs_flex import GtfsFlexAdapter
from packages.connect.gtfs_realtime import (
    GtfsRealtimeAdapter,
    feed_message_to_rows,
    read_gtfs_realtime_feed,
)
from packages.connect.operator_export import (
    REPAIR_RULES,
    OperatorExportAdapter,
    OperatorTripRecord,
    coerce_boolean_like,
    repair_rule_of,
    resolve_intake_columns,
)
from packages.connect.ingest_report import (
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
    "GtfsFlexAdapter",
    "GtfsRealtimeAdapter",
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
