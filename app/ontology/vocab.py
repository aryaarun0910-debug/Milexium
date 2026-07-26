"""Closed vocabularies for Ontology v1 (MX-ONT-DECISION-SNAPSHOT-013).

EVERY vocabulary in this module is CLOSED, and that is the point of the module
existing at all. A decision episode is only learnable from if the words it is
written in mean the same thing in the dispatcher's screen, the solver's input,
the evidence pack and the training set. An open string field is a place for two
of those four to disagree quietly, and the disagreement is discovered a year
later when a model has already been trained on it.

The rule this package follows, and where it deviates from
`app/canonical/entities.py`:

  * A value a consumer BRANCHES on is a closed enum here, and the portable DDL
    mirrors it as `CHECK (col IN (...))` (ADR-0002 bans ENUM types from the
    portable subset). An unrecognised value is then a rejected write, not a
    silently unhandled branch.
  * A value that is merely DETAIL carried from a source system stays a plain
    string on the record (a source's own status code, its own equipment name).
    `app/canonical/entities.py` keeps `current_status` and
    `schedule_relationship` as source strings for exactly this reason.

WHAT IS DELIBERATELY REUSED RATHER THAN RE-DECLARED.
`SensitivityClass` and `ReasonCode` are IMPORTED from `app/canonical/vocab.py`
and re-exported, not redefined. A second privacy vocabulary would be the exact
drift this module exists to prevent, and a redaction step that had to know which
of two enums a field was labelled with would be strictly worse than one.

STATUS: Demonstrated at most. Every fixture exercising these vocabularies is
synthetic -- there is no consented operator data in this repository -- so
nothing here is Validated, and the real-world completeness of several of these
sets is an open question recorded in the packet's `guesses_about_operator_data`.
"""

from __future__ import annotations

from enum import Enum

# Reused, never redefined -- see the module docstring.
from app.canonical.vocab import ReasonCode, SensitivityClass

__all__ = [
    "ReasonCode",
    "SensitivityClass",
    "ObjectKind",
    "RelationshipKind",
    "RELATIONSHIP_SIGNATURES",
    "EventKind",
    "ActionKind",
    "Permission",
    "ACTION_PERMISSIONS",
    "FactClass",
    "QualityState",
    "MissingnessReason",
    "LegalBasis",
    "RepairKind",
    "AuthorityKind",
    "VerifierVerdict",
]


# --------------------------------------------------------------------------- #
# Objects
# --------------------------------------------------------------------------- #
class ObjectKind(str, Enum):
    """The 28 kinds of thing a decision episode can be about.

    AN ONTOLOGY OBJECT CARRIES IDENTITY, NOT STATE -- the single most important
    modelling decision in this package. There is no `Vehicle.capacity` field
    anywhere in `app/ontology`: capacity is time-varying, so it is a FACT
    (`app/ontology/provenance.SnapshotFact`) with an observation time and a
    receipt time, and it is readable only through a point-in-time snapshot.

    Why it is built this way: if an object could carry an attribute directly,
    that attribute would have no receipt time, and a decision replayed at time T
    would read whatever the attribute says NOW. That is precisely how leakage
    enters a warehouse invisibly -- a "dimension table" holding today's value of
    a field the model was trained against as of last March. Making objects
    stateless means there is nowhere to put an un-timestamped attribute.

    The strongly-typed operational aggregates (`ServiceRequest`, `Vehicle`,
    `Block`, ...) continue to live in `app/canonical`, which is their home;
    this enum names the KINDS so relationships, events and actions can be typed
    across all of them, including the many kinds canonical has no table for yet
    (eligibility profile, protected zone, contract, service rule, incident,
    disruption, maintenance event, override).
    """

    OPERATOR = "operator"
    SERVICE_AREA = "service_area"
    DEPOT = "depot"
    RIDER = "rider"
    """A rider PSEUDONYM. Never a name; see `SensitivityClass.IDENTITY`."""
    ELIGIBILITY_PROFILE = "eligibility_profile"
    """What a rider is entitled to and needs (ADA paratransit eligibility,
    conditional eligibility, required equipment, PCA entitlement). Held as a
    SEPARATE object from the rider because it is re-certified on its own cycle
    and is health-adjacent data with a different legal basis and retention rule
    from the pseudonym it hangs off."""
    REQUEST = "request"
    JOURNEY = "journey"
    """A NEGOTIATED journey: what was actually agreed, as distinct from what was
    requested. Separate from `REQUEST` so "you asked for 08:00, we offered
    08:40" survives as two objects rather than one overwritten field."""
    LOCATION = "location"
    PROTECTED_ZONE = "protected_zone"
    """A geography whose precise coordinates must not leave the boundary --
    a refuge, a clinic, a shelter, a school. A first-class object so the
    protection is a property of the PLACE, applied to every request touching it,
    rather than a per-request flag someone has to remember to set."""
    VEHICLE = "vehicle"
    ACCESSIBILITY_EQUIPMENT = "accessibility_equipment"
    """A lift, a ramp, a securement position, an oxygen mount. First-class
    because a request REQUIRES equipment and a vehicle CARRIES it, and matching
    those two is the constraint whose violation is an accessibility denial."""
    CAPACITY_PROFILE = "capacity_profile"
    """A named seating/securement configuration a vehicle can be in. Separate
    from the vehicle because the same bus is reconfigured (fold-up seats raised
    or lowered) and its effective capacity is therefore a time-varying fact
    about a (vehicle, configuration) pair, not a constant of the vehicle.
    GUESS: that operators track this at all. See the packet."""
    DRIVER = "driver"
    SHIFT = "shift"
    RUN = "run"
    BLOCK = "block"
    ASSIGNMENT = "assignment"
    SCHEDULE_VERSION = "schedule_version"
    POLICY = "policy"
    CONTRACT = "contract"
    SERVICE_RULE = "service_rule"
    """One enforceable obligation derived from a contract or regulation -- an
    on-time-performance threshold, a maximum denial rate, a ride-time ceiling.
    Separate from `CONTRACT` because a single contract yields many rules with
    different measurement windows, and it is the RULE a decision is checked
    against."""
    INCIDENT = "incident"
    DISRUPTION = "disruption"
    MAINTENANCE_EVENT = "maintenance_event"
    FORECAST = "forecast"
    RECOMMENDATION = "recommendation"
    OVERRIDE = "override"
    OUTCOME = "outcome"


# --------------------------------------------------------------------------- #
# Relationships
# --------------------------------------------------------------------------- #
class RelationshipKind(str, Enum):
    """Relationships as FIRST-CLASS records, not foreign keys buried in tables.

    The difference is not stylistic. A foreign key column can hold exactly one
    value, has no time extent, cannot carry a probability, and cannot be
    contradicted without being overwritten. Every one of those four limits
    matters here:

      * ONE VALUE -- "this assignment consumed two likely future pooling
        opportunities" is a relationship with a cardinality the assignment row
        cannot hold.
      * NO TIME EXTENT -- a driver operates a vehicle FOR A PERIOD. A
        `driver_id` column on `vehicles` asserts it forever.
      * NO PROBABILITY -- `weight` on a relationship is what lets a *likely*
        foreclosed pooling opportunity be recorded as likely rather than as
        fact.
      * OVERWRITING -- a relationship here is asserted, never mutated;
        withdrawing it is a new record with an end time, so the decision that
        was made while it held is still explicable.
    """

    # -- the eleven the packet names --------------------------------------- #
    REQUEST_BELONGS_TO_RIDER = "request_belongs_to_rider"
    REQUEST_REQUIRES_EQUIPMENT = "request_requires_equipment"
    ASSIGNMENT_SERVES_REQUEST = "assignment_serves_request"
    VEHICLE_PERFORMS_ASSIGNMENT = "vehicle_performs_assignment"
    DRIVER_OPERATES_VEHICLE = "driver_operates_vehicle"
    RUN_BELONGS_TO_BLOCK = "run_belongs_to_block"
    RECOMMENDATION_CONSIDERED_ALTERNATIVE = "recommendation_considered_alternative"
    OVERRIDE_REPLACED_RECOMMENDATION = "override_replaced_recommendation"
    INCIDENT_AFFECTED = "incident_affected"
    POLICY_CONSTRAINED_DECISION = "policy_constrained_decision"
    OUTCOME_RESULTED_FROM = "outcome_resulted_from"

    # -- the ones the episode in the packet's own vignette also needs ------- #
    RIDER_HAS_ELIGIBILITY_PROFILE = "rider_has_eligibility_profile"
    JOURNEY_NEGOTIATED_FROM_REQUEST = "journey_negotiated_from_request"
    VEHICLE_CARRIES_EQUIPMENT = "vehicle_carries_equipment"
    VEHICLE_CONFIGURED_AS = "vehicle_configured_as"
    SHIFT_WORKED_BY_DRIVER = "shift_worked_by_driver"
    DISRUPTION_AFFECTED = "disruption_affected"
    MAINTENANCE_REMOVED_VEHICLE = "maintenance_removed_vehicle"
    CONTRACT_GOVERNS = "contract_governs"
    SERVICE_RULE_DERIVED_FROM_CONTRACT = "service_rule_derived_from_contract"
    FORECAST_INFORMED_RECOMMENDATION = "forecast_informed_recommendation"
    LOCATION_WITHIN_PROTECTED_ZONE = "location_within_protected_zone"
    ASSIGNMENT_FORECLOSED_POOLING_WITH = "assignment_foreclosed_pooling_with"
    """"This assignment consumed a likely future pooling opportunity with that
    request." The one relationship that is inherently PROBABILISTIC -- it is
    asserted with a `weight` and is meaningless without one, because the
    opportunity was never certain. It is the representational reason the
    packet's vignette cannot be written down in a foreign-key model."""


RELATIONSHIP_SIGNATURES: dict[
    RelationshipKind, tuple[frozenset[ObjectKind], frozenset[ObjectKind]]
] = {
    RelationshipKind.REQUEST_BELONGS_TO_RIDER: (
        frozenset({ObjectKind.REQUEST}),
        frozenset({ObjectKind.RIDER}),
    ),
    RelationshipKind.REQUEST_REQUIRES_EQUIPMENT: (
        frozenset({ObjectKind.REQUEST}),
        frozenset({ObjectKind.ACCESSIBILITY_EQUIPMENT}),
    ),
    RelationshipKind.ASSIGNMENT_SERVES_REQUEST: (
        frozenset({ObjectKind.ASSIGNMENT}),
        frozenset({ObjectKind.REQUEST, ObjectKind.JOURNEY}),
    ),
    RelationshipKind.VEHICLE_PERFORMS_ASSIGNMENT: (
        frozenset({ObjectKind.VEHICLE}),
        frozenset({ObjectKind.ASSIGNMENT}),
    ),
    RelationshipKind.DRIVER_OPERATES_VEHICLE: (
        frozenset({ObjectKind.DRIVER}),
        frozenset({ObjectKind.VEHICLE}),
    ),
    RelationshipKind.RUN_BELONGS_TO_BLOCK: (
        frozenset({ObjectKind.RUN}),
        frozenset({ObjectKind.BLOCK}),
    ),
    RelationshipKind.RECOMMENDATION_CONSIDERED_ALTERNATIVE: (
        frozenset({ObjectKind.RECOMMENDATION}),
        frozenset({ObjectKind.ASSIGNMENT, ObjectKind.RECOMMENDATION}),
    ),
    RelationshipKind.OVERRIDE_REPLACED_RECOMMENDATION: (
        frozenset({ObjectKind.OVERRIDE}),
        frozenset({ObjectKind.RECOMMENDATION}),
    ),
    RelationshipKind.INCIDENT_AFFECTED: (
        frozenset({ObjectKind.INCIDENT}),
        frozenset(
            {
                ObjectKind.VEHICLE,
                ObjectKind.SERVICE_AREA,
                ObjectKind.DEPOT,
                ObjectKind.DRIVER,
                ObjectKind.REQUEST,
            }
        ),
    ),
    RelationshipKind.POLICY_CONSTRAINED_DECISION: (
        frozenset({ObjectKind.POLICY, ObjectKind.SERVICE_RULE}),
        frozenset(
            {ObjectKind.RECOMMENDATION, ObjectKind.OVERRIDE, ObjectKind.ASSIGNMENT}
        ),
    ),
    RelationshipKind.OUTCOME_RESULTED_FROM: (
        frozenset({ObjectKind.OUTCOME}),
        frozenset(
            {ObjectKind.ASSIGNMENT, ObjectKind.OVERRIDE, ObjectKind.RECOMMENDATION}
        ),
    ),
    RelationshipKind.RIDER_HAS_ELIGIBILITY_PROFILE: (
        frozenset({ObjectKind.RIDER}),
        frozenset({ObjectKind.ELIGIBILITY_PROFILE}),
    ),
    RelationshipKind.JOURNEY_NEGOTIATED_FROM_REQUEST: (
        frozenset({ObjectKind.JOURNEY}),
        frozenset({ObjectKind.REQUEST}),
    ),
    RelationshipKind.VEHICLE_CARRIES_EQUIPMENT: (
        frozenset({ObjectKind.VEHICLE}),
        frozenset({ObjectKind.ACCESSIBILITY_EQUIPMENT}),
    ),
    RelationshipKind.VEHICLE_CONFIGURED_AS: (
        frozenset({ObjectKind.VEHICLE}),
        frozenset({ObjectKind.CAPACITY_PROFILE}),
    ),
    RelationshipKind.SHIFT_WORKED_BY_DRIVER: (
        frozenset({ObjectKind.SHIFT}),
        frozenset({ObjectKind.DRIVER}),
    ),
    RelationshipKind.DISRUPTION_AFFECTED: (
        frozenset({ObjectKind.DISRUPTION}),
        frozenset(
            {
                ObjectKind.SERVICE_AREA,
                ObjectKind.BLOCK,
                ObjectKind.RUN,
                ObjectKind.DEPOT,
            }
        ),
    ),
    RelationshipKind.MAINTENANCE_REMOVED_VEHICLE: (
        frozenset({ObjectKind.MAINTENANCE_EVENT}),
        frozenset({ObjectKind.VEHICLE}),
    ),
    RelationshipKind.CONTRACT_GOVERNS: (
        frozenset({ObjectKind.CONTRACT}),
        frozenset({ObjectKind.SERVICE_AREA, ObjectKind.OPERATOR}),
    ),
    RelationshipKind.SERVICE_RULE_DERIVED_FROM_CONTRACT: (
        frozenset({ObjectKind.SERVICE_RULE}),
        frozenset({ObjectKind.CONTRACT}),
    ),
    RelationshipKind.FORECAST_INFORMED_RECOMMENDATION: (
        frozenset({ObjectKind.FORECAST}),
        frozenset({ObjectKind.RECOMMENDATION}),
    ),
    RelationshipKind.LOCATION_WITHIN_PROTECTED_ZONE: (
        frozenset({ObjectKind.LOCATION}),
        frozenset({ObjectKind.PROTECTED_ZONE}),
    ),
    RelationshipKind.ASSIGNMENT_FORECLOSED_POOLING_WITH: (
        frozenset({ObjectKind.ASSIGNMENT}),
        frozenset({ObjectKind.REQUEST, ObjectKind.JOURNEY}),
    ),
}
"""Which object kinds may sit on each end of each relationship.

THE LEGALITY TABLE IS THE POINT. Without it, "relationships are first-class"
means only "we put them in their own table", and an `INCIDENT_AFFECTED` edge
from a policy to a forecast would insert cleanly and be discovered by whoever
next wrote a query over it. With it, the edge is rejected at construction and
by a store write, so the graph's shape is a schema rather than a convention.

A conformance test asserts this table is TOTAL over `RelationshipKind` -- adding
a relationship kind without a signature fails the suite rather than defaulting
to "anything goes", which is the failure mode a permissive default would have.
"""


# --------------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------------- #
class EventKind(str, Enum):
    """What happened, in the operational world, that the ontology recorded.

    Distinct from `ActionKind` below, and the distinction is load-bearing: an
    EVENT is something the world did (a rider cancelled, a vehicle broke down),
    an ACTION is something Milexium or a dispatcher DID, with an authority, an
    input snapshot and a predicted effect. Collapsing the two is how a system
    ends up unable to say whether it caused an outcome or merely observed one.
    """

    BOOKING_CREATED = "booking_created"
    BOOKING_AMENDED = "booking_amended"
    WINDOW_NEGOTIATED = "window_negotiated"
    ASSIGNMENT_CREATED = "assignment_created"
    ASSIGNMENT_MOVED = "assignment_moved"
    VEHICLE_DELAYED = "vehicle_delayed"
    VEHICLE_UNAVAILABLE = "vehicle_unavailable"
    RIDER_CANCELLED = "rider_cancelled"
    RIDER_NO_SHOWED = "rider_no_showed"
    DISPATCHER_OVERRODE = "dispatcher_overrode"
    ARRIVAL = "arrival"
    PICKUP = "pickup"
    DROPOFF = "dropoff"
    TRIP_DENIED = "trip_denied"
    TRIP_MISSED = "trip_missed"
    POLICY_CHANGED = "policy_changed"


# --------------------------------------------------------------------------- #
# Actions and permissions
# --------------------------------------------------------------------------- #
class ActionKind(str, Enum):
    """The complete set of operations that may change operational state.

    THERE IS NO TWELFTH. `app/ontology/store.py` exposes no generic write
    against the operational tables -- an effect is reachable only by naming one
    of these, and naming one requires an `Authority` holding its permission, an
    input snapshot, and the alternatives that were considered. "Arbitrary
    database write" is not a discouraged pattern here; it is an absent code
    path, and a conformance test asserts the store's public surface contains no
    method that writes an effect without an action record.
    """

    ACCEPT_REQUEST = "accept_request"
    NEGOTIATE_REQUEST = "negotiate_request"
    ASSIGN = "assign"
    REASSIGN = "reassign"
    HOLD_CAPACITY = "hold_capacity"
    REPOSITION_CAPACITY = "reposition_capacity"
    COMBINE_TRIPS = "combine_trips"
    CALL_IN_SPARE_CAPACITY = "call_in_spare_capacity"
    ESCALATE_ACCESSIBILITY_RISK = "escalate_accessibility_risk"
    APPROVE_RECOMMENDATION = "approve_recommendation"
    REJECT_RECOMMENDATION = "reject_recommendation"


class Permission(str, Enum):
    """What an authority is allowed to do. Deliberately COARSER than
    `ActionKind`: several actions share a permission because they are the same
    trust decision (assigning and reassigning are both "may write assignments").

    Coarser, but not one blanket permission -- the three that are genuinely
    different trust decisions stay separate:
      * `SPARE_CAPACITY_CALL` costs money outside the schedule.
      * `ACCESSIBILITY_ESCALATE` reaches a human on an equity-critical path.
      * `RECOMMENDATION_DECIDE` is the human-authority gate on automation.
    """

    REQUEST_ACCEPT = "request.accept"
    REQUEST_NEGOTIATE = "request.negotiate"
    ASSIGNMENT_WRITE = "assignment.write"
    CAPACITY_MANAGE = "capacity.manage"
    TRIP_COMBINE = "trip.combine"
    SPARE_CAPACITY_CALL = "spare_capacity.call"
    ACCESSIBILITY_ESCALATE = "accessibility.escalate"
    RECOMMENDATION_DECIDE = "recommendation.decide"


ACTION_PERMISSIONS: dict[ActionKind, Permission] = {
    ActionKind.ACCEPT_REQUEST: Permission.REQUEST_ACCEPT,
    ActionKind.NEGOTIATE_REQUEST: Permission.REQUEST_NEGOTIATE,
    ActionKind.ASSIGN: Permission.ASSIGNMENT_WRITE,
    ActionKind.REASSIGN: Permission.ASSIGNMENT_WRITE,
    ActionKind.HOLD_CAPACITY: Permission.CAPACITY_MANAGE,
    ActionKind.REPOSITION_CAPACITY: Permission.CAPACITY_MANAGE,
    ActionKind.COMBINE_TRIPS: Permission.TRIP_COMBINE,
    ActionKind.CALL_IN_SPARE_CAPACITY: Permission.SPARE_CAPACITY_CALL,
    ActionKind.ESCALATE_ACCESSIBILITY_RISK: Permission.ACCESSIBILITY_ESCALATE,
    ActionKind.APPROVE_RECOMMENDATION: Permission.RECOMMENDATION_DECIDE,
    ActionKind.REJECT_RECOMMENDATION: Permission.RECOMMENDATION_DECIDE,
}
"""The permission each action requires. TOTAL over `ActionKind` -- asserted by
conformance, so a new action kind cannot arrive permissionless and default to
allowed."""


class AuthorityKind(str, Enum):
    """Who exercised an action. The same two-value vocabulary
    `decision_events.actor_type` and `RequestTransition.actor_type` already use
    ('system' | 'human'), plus the third case those two cannot express.
    """

    SYSTEM = "system"
    HUMAN = "human"
    HUMAN_ON_BEHALF_OF_SYSTEM = "human_on_behalf_of_system"
    """A human clicking "accept" on a recommendation the system produced. It is
    NEITHER of the other two: recording it as `system` erases the human
    accountability, and recording it as `human` erases that the content was
    machine-generated -- and the difference is precisely what a regulator asking
    "was this decision automated?" is asking about."""


class VerifierVerdict(str, Enum):
    """What the independent checker said about a proposed action, before it ran.

    `NOT_RUN` is a real, recordable verdict and not a null: an action taken
    without verification is a materially different act from a verified one, and
    the difference must survive into the training set rather than looking like a
    missing column.
    """

    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    NOT_RUN = "not_run"
    UNAVAILABLE = "unavailable"


# --------------------------------------------------------------------------- #
# Fact provenance vocabularies
# --------------------------------------------------------------------------- #
class FactClass(str, Enum):
    """What KIND of claim a fact makes -- and the field the information-set
    boundary's one non-trivial invariant is keyed on.

    An `OBSERVATION` is a claim about something that has already happened, so
    its observation time can never be later than the instant it was received
    (`app/ontology/provenance.py` rejects that at construction). A
    `PREDICTION` is a claim about a time that may be in the future, which is
    legitimate and must stay legitimate -- the whole product forecasts.

    Together those two rules give the snapshot a THEOREM rather than a check:
    since a snapshot admits a fact only when `receipt_time < as_of`, and an
    observation satisfies `observed_at <= receipt_time`, every OBSERVATION in a
    snapshot is necessarily about the strict past. No separate filter on
    observation time is needed, and none is applied -- which matters, because a
    second filter would have had to make an exception for predictions and the
    exception would have been the hole.
    """

    OBSERVATION = "observation"
    PREDICTION = "prediction"
    PLAN = "plan"
    """An intention: a scheduled pickup, a planned pull-out. Like a prediction
    it may refer to the future; unlike a prediction it is not probabilistic."""
    DERIVATION = "derivation"
    """Computed from other facts (a rolling mean, a headway). Carries the
    receipt time of its computation, which is >= that of every input."""
    DECLARATION = "declaration"
    """Asserted by a party rather than observed: an eligibility determination, a
    contractual threshold, an operator's own classification of an incident."""


class QualityState(str, Enum):
    """How much weight the fact will bear.

    `CONFLICTED` is the state that stops an averaging bug: two sources disagreed
    and neither was chosen. It is recorded as a state, with both values retained
    as separate facts, rather than resolved by picking one -- the same
    discipline `app/ontology/provenance.IdentityResolution` applies to
    identity matches.
    """

    TRUSTED = "trusted"
    PROVISIONAL = "provisional"
    REPAIRED = "repaired"
    SUSPECT = "suspect"
    CONFLICTED = "conflicted"


class MissingnessReason(str, Enum):
    """WHY a field has no value. Recorded because "null" is not one fact but at
    least nine, and a model trained on undifferentiated nulls learns the
    operator's data-collection habits as if they were rider behaviour.

    The distinction that matters most commercially is the first three:
    `NOT_COLLECTED` (the operator never records it) is a data-acquisition
    conversation; `NOT_APPLICABLE` (an ambulatory rider has no securement
    requirement) is a genuine structural zero and must never be imputed;
    `NOT_YET_KNOWN` (the trip has not finished) is the one that becomes known
    later, and is therefore the one that leaks if a snapshot is rebuilt
    carelessly.
    """

    NOT_COLLECTED = "not_collected"
    NOT_APPLICABLE = "not_applicable"
    NOT_YET_KNOWN = "not_yet_known"
    SUPPRESSED_PRIVACY = "suppressed_privacy"
    SUPPRESSED_LEGAL = "suppressed_legal"
    SOURCE_UNAVAILABLE = "source_unavailable"
    FAILED_VALIDATION = "failed_validation"
    WITHHELD_BY_OPERATOR = "withheld_by_operator"
    UNRESOLVED_IDENTITY = "unresolved_identity"
    """The value exists in the source but could not be attached to an object
    with sufficient confidence. See `IdentityResolution`: the candidates are
    retained, so this missingness is recoverable rather than terminal."""


class LegalBasis(str, Enum):
    """The lawful basis on which Milexium holds and uses the field.

    Per-FIELD, not per-table, for the same reason `SensitivityClass` is: a
    request row mixes a pseudonym held to perform a contract with a health-
    adjacent eligibility flag that may rest on a different basis entirely, and a
    table-level label would force the strictest rule onto everything or the
    loosest onto the pseudonym.

    `NOT_ESTABLISHED` is the honest default and the only safe one: it is what an
    ingest with no rights record produces, and `app/ontology/store.py`
    refuses to admit such a fact into a snapshot used for MODEL TRAINING while
    still admitting it for OPERATIONAL dispatch -- the two uses do not have the
    same footing, and collapsing them is how a training set quietly acquires
    data nobody agreed to.
    """

    CONTRACT_PERFORMANCE = "contract_performance"
    LEGAL_OBLIGATION = "legal_obligation"
    LEGITIMATE_INTEREST = "legitimate_interest"
    CONSENT = "consent"
    VITAL_INTEREST = "vital_interest"
    PUBLIC_TASK = "public_task"
    ANONYMISED_AGGREGATE = "anonymised_aggregate"
    NOT_ESTABLISHED = "not_established"


class RepairKind(str, Enum):
    """What was done to a value between the source and the store.

    REPAIR LINEAGE POINTS BACKWARD ONLY. A repaired fact names the fact it
    repairs (`repairs_fact_id`); the repaired-FROM fact is never updated to
    point forward at its successor. That is not a convenience -- a forward
    pointer would require mutating a row that an already-taken snapshot has
    admitted, which is exactly the write these tables refuse. Walking lineage
    forwards is a query (`WHERE repairs_fact_id = ?`), and a query cannot
    contaminate the past.
    """

    NONE = "none"
    UNIT_NORMALISED = "unit_normalised"
    TIMEZONE_RESOLVED = "timezone_resolved"
    DEDUPLICATED = "deduplicated"
    IMPUTED = "imputed"
    RANGE_CLAMPED = "range_clamped"
    CODE_MAPPED = "code_mapped"
    PARSED_FROM_FREE_TEXT = "parsed_from_free_text"
    MANUALLY_CORRECTED = "manually_corrected"
