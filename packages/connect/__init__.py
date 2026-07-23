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

__all__ = [
    "AdapterResult",
    "QuarantinedRow",
    "SemanticLossRecord",
    "SourceAdapter",
    "parse_batch",
    "ReferenceAgencyTripsAdapter",
]

CONTRACT_VERSION = "0.1.0"
