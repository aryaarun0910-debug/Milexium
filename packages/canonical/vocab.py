"""Policy, metric, and sensitivity vocabularies (Program A contract).

Kept as a small, closed set on purpose -- the expansion plan's "expansion
rule" (blueprint/01-north-star-and-boundaries.md) says the shared core owns
only concepts invariant across at least two adapters. Reason codes here are
exactly the set already committed to in docs/MASTER_ROADMAP.md; this module
exists so that commitment has one canonical definition instead of being
re-typed (and able to drift) in the scheduler, the evidence exports, and the
verifier separately.
"""

from __future__ import annotations

from enum import Enum


class ReasonCode(str, Enum):
    """Scheduling explanation reason codes. Never SHAP output or generated prose."""

    NO_ACCESSIBLE_CAPACITY = "NO_ACCESSIBLE_CAPACITY"
    PICKUP_WINDOW = "PICKUP_WINDOW"
    DROPOFF_WINDOW = "DROPOFF_WINDOW"
    MAX_RIDE_TIME = "MAX_RIDE_TIME"
    SHIFT_END = "SHIFT_END"
    PRECEDENCE = "PRECEDENCE"
    SOLVER_TIMEOUT = "SOLVER_TIMEOUT"


class SensitivityClass(str, Enum):
    """Data-minimization classification (blueprint/10-security-privacy-and-ai-governance.md).

    Attached to fields, not just tables, so an export/redaction step can act
    field-by-field rather than trusting a table-level label.
    """

    OPERATIONAL = "operational"
    """Requirement/capability facts needed for scheduling (e.g. mobility device)."""

    IDENTITY = "identity"
    """Tokenized identity references. Never a raw name in a canonical record."""

    PRECISE_LOCATION = "precise_location"
    """Exact pickup/dropoff coordinates -- generalize or redact in analytics/exports."""

    FREE_TEXT = "free_text"
    """Unstructured notes. Excluded from general model features by default."""


class DecisionEventType(str, Enum):
    RECOMMENDATION = "recommendation"
    REJECTION = "rejection"
    OVERRIDE = "override"
    OUTCOME_RECORDED = "outcome_recorded"


class ScheduleRunStatus(str, Enum):
    OPTIMAL = "optimal"
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    TIMEOUT = "timeout"
