"""The operator data contract: what we must ask an agency for, and what each
field buys.

STATUS AND SCOPE, FIRST, BECAUSE THEY BOUND EVERYTHING BELOW
Milexium holds **zero operator data**. Nothing in this repository is Validated
(ADR-0001), no pilot exists, and no agency has sent anything. This module is not
an integration, not a connector, and not a schema for a system we have talked to.
It is the **contract**: the precise, answerable statement of what an operator
would have to send for each specific claim we might later want to make -- written
so an agency's IT lead can read it line by line and answer *yes / no / we do not
record that*, and so an operations director can read the companion document
without a schema in front of them.

WHY IT EXISTS AS CODE RATHER THAN A DOCUMENT
ADR-0038 already publishes an intake document (`forge/knowledge/docs/
OPERATOR_DATA_INTAKE.md`) and ADR-0051 already publishes the adapter that
enforces it. Both answer "how do we receive a trip export". Neither answers the
question ADR-0072 closes on, which is a different question:

    Our receipt time is a proxy for the operator's knowledge time. If their
    system knew at 10:30 and exported at 11:00, our 10:45 snapshot correctly
    excludes it -- correct for us, but THE DISPATCHER KNEW. Replaying their
    decisions against that snapshot credits them with less information than they
    had, and biases every "we would have done better" comparison IN OUR FAVOUR.

That is a data-acquisition problem with a deadline attached: a source-side
knowledge timestamp cannot be retrofitted onto history that has already been
exported without one. So the contract has to exist *before* the data arrives, and
it has to be checkable rather than aspirational -- hence a source of truth in
Python, two generated artifacts derived from it, and a validator
(`talos/contracts/validate_operator_export.py`) that reads a sample export and
reports which of these capabilities it can and cannot support.

THE RULE THIS FILE IS WRITTEN UNDER
Every field states what it unlocks and what is lost without it. A field that
cannot state both does not belong here. An operator asked for everything gives
nothing, and asking for data we have no use for is how credibility is spent
before the first analysis is run.

GENERATED FROM THIS MODULE (do not hand-edit either):
  talos/contracts/jsonschema/operator-data-contract-v0.1.json   -- machine-readable
  talos/contracts/OPERATOR_DATA_CONTRACT.md                     -- human-readable

Regenerate with:  py -3 talos/contracts/generate.py
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

CONTRACT_ID = "operator-data-contract"
CONTRACT_VERSION = "0.1"
CONTRACT_DATE = "2026-07-26"

# The published intake document and the adapter that enforces it. This contract
# EXTENDS them and deliberately does not restate their required column list in a
# different shape -- an operator who has read one and then reads the other must
# not find two different minimum asks.
INTAKE_DOCUMENT = "forge/knowledge/docs/OPERATOR_DATA_INTAKE.md"
INTAKE_ADAPTER = "themis/connect/operator_export.py"


class Requirement(str, Enum):
    """What happens when the field is absent. Each level is defined by its
    consequence, not by how much we would like to have it."""

    REQUIRED = "required"
    """For a COLUMN: without it we decline the export rather than produce a
    number we cannot defend. This set is deliberately IDENTICAL to the one
    ADR-0038 already published -- this contract adds no new mandatory column.

    For a DECLARATION: we do not start without an answer. Each of the six
    changes how the file must be READ, so beginning before they are answered
    means producing figures whose meaning is not yet settled. Each costs one
    line of an email, and "we do not record that" is an acceptable answer to
    every one of them."""

    REQUIRED_FOR_REPLAY = "required_for_replay"
    """The export is still worth sending without it, and outcome analysis still
    works. One specific thing -- reconstructing what was knowable at a decision
    instant, and therefore any honest "a different decision would have done
    better" comparison -- becomes impossible, and we say so in the output rather
    than quietly degrading into a claim we cannot support."""

    HELPFUL = "helpful"
    """Unlocks one named capability. Its absence narrows that capability in a
    way we can state precisely, and nothing else."""


class Shape(str, Enum):
    """How the operator supplies it. Two thirds of the required set are not
    columns at all -- they are one-line answers to questions, which is the
    cheapest thing we ask for and the part most likely to be skipped."""

    COLUMN = "column"
    """A column in the trip export."""

    DECLARATION = "declaration"
    """A written answer, not data. An email is sufficient."""

    TABLE = "table"
    """A second, small file alongside the trip export."""


ANSWER_OPTIONS: tuple[str, ...] = ("yes", "no", "we do not record that")
"""Every line in this contract is answerable with one of these three. The third
is not a failure: "we do not record that" is the answer that tells us what we
may never claim, and it is more useful than a guess."""


@dataclass(frozen=True)
class Capability:
    """A question we could answer for the operator, and the fields it costs.

    Capabilities are the unit of honesty in this contract. A field is not
    justified by being interesting; it is justified by being the reason one of
    these moves from "we cannot answer that" to "we can".
    """

    id: str
    name: str
    question_it_answers: str
    requires: tuple[str, ...]
    """Field names that must ALL be present."""
    requires_any: tuple[str, ...] = ()
    """Field names of which at least ONE must be present."""
    sharpened_by: tuple[str, ...] = ()
    """Present -> the answer is a measurement. Absent -> it is a bound, and the
    validator says which."""


@dataclass(frozen=True)
class FieldSpec:
    """One line an operator's IT lead can answer yes / no / we-do-not-record-that."""

    name: str
    shape: Shape
    value_type: str
    requirement: Requirement
    summary: str
    """What it is, in the operator's language, not ours."""
    unlocks: str
    """What capability it buys. Concrete, and never a benefit claim."""
    lost_without_it: str
    """What we can no longer say. This is the half that keeps the ask honest."""
    operator_question: str
    """The question, phrased so it can be answered without reading the rest."""
    conditional_on: str | None = None
    """Set when the requirement only bites in a stated circumstance."""
    note: str | None = None


@dataclass(frozen=True)
class NotRequested:
    """Something an operator's system almost certainly holds, that we are not
    asking for. Recorded explicitly, because a field list without this section
    reads as "send everything you have" no matter what the header says."""

    name: str
    why_not: str
    what_we_give_up: str
    when_we_would_ask: str


@dataclass(frozen=True)
class Refusal:
    """Something we will not accept even if offered. Distinct from
    `NotRequested`: this is a gate, not an omission."""

    category: str
    example_columns: tuple[str, ...]
    why: str


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------

CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        id="outcome_analysis",
        name="Outcome analysis",
        question_it_answers=(
            "How did the service actually perform -- lateness against the promised "
            "pickup, denial rate, no-show rate, demand by zone and hour?"
        ),
        requires=(
            "trip_ref",
            "requested_at",
            "scheduled_pickup_at",
            "actual_pickup_at",
            "pickup_zone",
            "dropoff_zone",
            "outcome",
            "export_generated_at",
            "coverage_window",
            "timestamp_convention",
            "source_systems",
        ),
        sharpened_by=("scheduled_dropoff_at", "outcome_known_at", "field_authority_map"),
    ),
    Capability(
        id="deadhead_measurement",
        name="Deadhead measurement",
        question_it_answers=(
            "How much of the fleet's day was spent running empty between one "
            "trip's dropoff and the next trip's pickup?"
        ),
        requires=("pickup_zone", "dropoff_zone", "scheduled_pickup_at", "fleet_shape"),
        requires_any=("vehicle_ref", "run_ref"),
        sharpened_by=("actual_dropoff_at", "trip_distance"),
    ),
    Capability(
        id="unmet_demand_forecasting",
        name="Unmet-demand forecasting",
        question_it_answers=(
            "What demand did you turn away, and would a forecast have seen it "
            "coming far enough ahead to do something about it?"
        ),
        requires=("requested_at", "pickup_zone", "outcome"),
    ),
    Capability(
        id="information_set_replay",
        name="Information-set replay",
        question_it_answers=(
            "What did your system know at 10:45 on a given morning -- which "
            "bookings existed, and which had not been entered yet?"
        ),
        requires=("record_created_known_at",),
        sharpened_by=("knowledge_time_source",),
    ),
    Capability(
        id="intraday_state_replay",
        name="Intra-day state replay",
        question_it_answers=(
            "What did the dispatcher's board LOOK LIKE at 10:45 -- including the "
            "trips that had already been cancelled, reassigned or re-timed by then?"
        ),
        requires=("record_created_known_at", "record_updated_known_at"),
    ),
    Capability(
        id="counterfactual_comparison",
        name="Counterfactual comparison",
        question_it_answers=(
            "Would a different assignment have done better than the one that was "
            "made -- judged only on what was knowable at the time?"
        ),
        requires=(
            "record_created_known_at",
            "alternatives_logged",
            "run_roster",
        ),
        sharpened_by=("record_updated_known_at", "candidate_log"),
    ),
    Capability(
        id="denial_analysis",
        name="Denial analysis",
        question_it_answers=(
            "Why were trips refused, in your vocabulary rather than ours -- and "
            "which of those reasons were capacity and which were policy?"
        ),
        requires=("denial_code", "denial_code_list"),
    ),
)


# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------

_TS = "timestamp, ISO-8601, with UTC offset (2026-03-04T08:15:00-05:00)"
_OPAQUE = "string, opaque to us"

FIELDS: tuple[FieldSpec, ...] = (
    # -- REQUIRED columns: unchanged from ADR-0038 -----------------------------
    FieldSpec(
        name="trip_ref",
        shape=Shape.COLUMN,
        value_type=_OPAQUE,
        requirement=Requirement.REQUIRED,
        summary="Your own booking or trip reference. We never resolve it back to anything.",
        unlocks="Every row-level statement we make. It is the handle a corrected re-send is matched on, and the key that lets a second export of the same period be reconciled with the first rather than double-counted.",
        lost_without_it="We cannot tell a re-sent correction from a duplicate trip, so a second export can only replace the first wholesale. Nothing we report can be traced back to a row you can look up.",
        operator_question="Does every exported row carry a stable trip or booking reference that stays the same if the row is later corrected and re-sent?",
    ),
    FieldSpec(
        name="requested_at",
        shape=Shape.COLUMN,
        value_type=_TS,
        requirement=Requirement.REQUIRED,
        summary="When the trip was booked or requested.",
        unlocks="Booking lead time, and the demand signal itself: demand is when people ask, not when they travel.",
        lost_without_it="A trip booked three weeks ahead and one booked at 06:00 the same morning become the same event. Lead-time distribution, same-day demand and any forecast horizon shorter than a service day all disappear.",
        operator_question="Is the booking/request timestamp exported, and is it the time the request was made rather than the time the record was last touched?",
    ),
    FieldSpec(
        name="scheduled_pickup_at",
        shape=Shape.COLUMN,
        value_type=_TS,
        requirement=Requirement.REQUIRED,
        summary="The pickup time you promised or scheduled.",
        unlocks="The promise half of on-time performance -- the thing lateness is measured against.",
        lost_without_it="Lateness is undefined. There is nothing to be late relative to, and any on-time figure would be invented.",
        operator_question="Is the promised or scheduled pickup time exported for every trip, including trips that were later cancelled?",
    ),
    FieldSpec(
        name="actual_pickup_at",
        shape=Shape.COLUMN,
        value_type=_TS,
        requirement=Requirement.REQUIRED,
        conditional_on="outcome = served",
        summary="When the pickup actually happened. Blank for trips that were not served.",
        unlocks="Realised lateness, which is the single number the whole teardown is about.",
        lost_without_it="On-time performance cannot be computed at all. We will not substitute the scheduled time for the actual one -- the gap between them is the measurement.",
        operator_question="For served trips, is an actual pickup time recorded (AVL, driver console, or manual), and is it exported?",
    ),
    FieldSpec(
        name="pickup_zone",
        shape=Shape.COLUMN,
        value_type="string -- a ZONE, never an address (ZONE-NW-3, Downtown, 90210, a TAZ, a grid cell)",
        requirement=Requirement.REQUIRED,
        summary="The geography you already schedule against, at the coarsest granularity that still means something to you.",
        unlocks="Origin-destination structure, demand by area, and the spatial half of deadhead.",
        lost_without_it="Every trip becomes placeless. Demand cannot be attributed to an area, and deadhead cannot be estimated even when the vehicle chain exists.",
        operator_question="Can pickup geography be exported as a zone, district, ZIP or grid cell rather than a street address?",
        note="Anything coarser than an address is fine. Anything that could be a doorstep is not, and is refused -- see the refusals section.",
    ),
    FieldSpec(
        name="dropoff_zone",
        shape=Shape.COLUMN,
        value_type="string -- a ZONE, never an address",
        requirement=Requirement.REQUIRED,
        summary="The same, for the destination.",
        unlocks="The destination half of origin-destination structure, and the start point of the empty leg to the next trip.",
        lost_without_it="Deadhead becomes unmeasurable in space: we would know a vehicle finished one trip and started another, but not how far apart they were.",
        operator_question="Can dropoff geography be exported as a zone rather than a street address?",
    ),
    FieldSpec(
        name="vehicle_ref",
        shape=Shape.COLUMN,
        value_type=_OPAQUE,
        requirement=Requirement.REQUIRED,
        conditional_on="at least one of vehicle_ref / run_ref",
        summary="Vehicle or unit number, as your fleet numbers it.",
        unlocks="Chaining one vehicle's consecutive trips, which is the ONLY way deadhead is measurable.",
        lost_without_it="Trips cannot be put in the order one vehicle performed them, so the empty time between them does not exist as a quantity. A row naming neither vehicle nor run is unusable by the teardown.",
        operator_question="Does each trip row name the vehicle that performed it, or the run/block it belonged to? Either is enough; both is better.",
        note="Read the fleet-shape declaration below before exporting this. In an owner-operator fleet a vehicle id is a person id, and the question is fleet shape, not column name (ADR-0057).",
    ),
    FieldSpec(
        name="run_ref",
        shape=Shape.COLUMN,
        value_type=_OPAQUE,
        requirement=Requirement.REQUIRED,
        conditional_on="at least one of vehicle_ref / run_ref",
        summary="Run, block or manifest id -- a day's chained work.",
        unlocks="The same chaining as vehicle_ref, and additionally the boundary of a shift, so 'the vehicle was idle' can be separated from 'the run had ended'.",
        lost_without_it="Idle time and off-shift time are indistinguishable, so deadhead is overstated by every hour a vehicle was legitimately not working.",
        operator_question="Is a run, block or manifest id carried on each trip?",
    ),
    FieldSpec(
        name="outcome",
        shape=Shape.COLUMN,
        value_type="one of: served, no_show, denied, cancelled (your own synonyms are mapped explicitly, never guessed)",
        requirement=Requirement.REQUIRED,
        summary="What happened to the trip.",
        unlocks="Separating 'happened late' from 'did not happen', and denial and no-show rates.",
        lost_without_it="A trip that was refused and a trip that was never requested look identical. Every rate we could compute would have an unknown denominator.",
        operator_question="Is a trip status exported for every row, and can you send us your status code list so we map it explicitly rather than by resemblance?",
    ),
    # -- REQUIRED declarations: six questions, one line each --------------------
    FieldSpec(
        name="export_generated_at",
        shape=Shape.DECLARATION,
        value_type=_TS,
        requirement=Requirement.REQUIRED,
        summary="When the extract was actually run.",
        unlocks="The ceiling on what can be in the file. It is also the control that catches a knowledge timestamp which is really the export time under another name -- the failure mode that would make the most important field in this contract look present and be worthless.",
        lost_without_it="A missing row is ambiguous between 'it did not happen' and 'it had not been entered when the extract ran', and we would have no way to detect a knowledge timestamp stamped by the export tool.",
        operator_question="What date and time was this extract run?",
    ),
    FieldSpec(
        name="coverage_window",
        shape=Shape.DECLARATION,
        value_type="two dates, plus a yes/no on completeness",
        requirement=Requirement.REQUIRED,
        summary="The period the export is meant to cover, and whether it is complete over that period.",
        unlocks="Telling a quiet Sunday apart from a missing day. It is what makes any rate we report a rate rather than a count of whatever happened to be in the file.",
        lost_without_it="A gap in the data is indistinguishable from a gap in the service. Every per-day and per-hour figure silently inherits the shape of the extract rather than the shape of the service.",
        operator_question="What period does this extract cover, is it complete over that period, and were any trip types, contractors or funding streams excluded?",
    ),
    FieldSpec(
        name="timestamp_convention",
        shape=Shape.DECLARATION,
        value_type="one of: UTC / local with offset / local without offset (name the zone) / mixed",
        requirement=Requirement.REQUIRED,
        summary="How to read the timestamps in the file.",
        unlocks="Reading the clock correctly. Nothing else.",
        lost_without_it="We assume UTC, which shifts every trip by your local offset. Every on-time number, every hour-of-day bucket and every headway would be wrong while looking perfectly well-formed -- the worst failure shape, because nothing about the output announces it.",
        operator_question="Are the timestamps UTC, or local time? If local, is the UTC offset included in the string, and does it change across a daylight-saving boundary inside the export period?",
    ),
    FieldSpec(
        name="fleet_shape",
        shape=Shape.DECLARATION,
        value_type="yes/no, plus a count if yes",
        requirement=Requirement.REQUIRED,
        summary="Whether any vehicle in the export is operated by exactly one person.",
        unlocks="Knowing whether vehicle_ref is a vehicle id or a person id. It decides whether we can accept the column at all.",
        lost_without_it="We fail closed and withhold every vehicle-level analysis, because in a fleet where vehicle and driver are one-to-one a vehicle number is a pseudonymous person identifier no matter what the column is called. We will not guess this from the data.",
        operator_question="Is any vehicle in this export driven by exactly one person -- an owner-operator, a sole contractor, a single-vehicle subcontractor? How many?",
        note="This is the ADR-0057 question, and it is asked as a question because it cannot be inferred from a column name. If the answer is yes, tokenise vehicle_ref before export or send run_ref instead.",
    ),
    FieldSpec(
        name="source_systems",
        shape=Shape.DECLARATION,
        value_type="a list of system names, and which fields each one produced",
        requirement=Requirement.REQUIRED,
        summary="Which of your systems this export was assembled from.",
        unlocks="Knowing whether two fields can disagree at all. One system cannot contradict itself; a booking system joined to an AVL feed joined to a dispatch console can, and does.",
        lost_without_it="Conflicting values have no precedence rule, so we either pick one silently -- which is the failure this whole repository is built to avoid -- or stop and ask you, mid-analysis.",
        operator_question="Was this export produced by one system or assembled from several? Name them, and say which fields came from which.",
    ),
    FieldSpec(
        name="alternatives_logged",
        shape=Shape.DECLARATION,
        value_type="one of: yes / no / we do not know",
        requirement=Requirement.REQUIRED,
        summary="Whether your scheduler records the candidate assignments it rejected, not just the one it chose.",
        unlocks="The difference between 'nothing else was considered' and 'we do not know what else was considered'. Those are different facts and only one of them is a finding.",
        lost_without_it="Backfilled decisions would carry an empty alternatives list, which reads as a claim that no alternative existed. That is a fabricated finding, and a flattering one, since it makes every decision look forced.",
        operator_question="Does your scheduling system log the vehicle/run candidates it evaluated and rejected for a trip? If it does, are those logs retained for the export period?",
        note="A 'no' here is a completely acceptable answer and changes nothing about whether the export is worth sending. What it changes is what we are allowed to conclude.",
    ),
    # -- REQUIRED FOR REPLAY ----------------------------------------------------
    FieldSpec(
        name="record_created_known_at",
        shape=Shape.COLUMN,
        value_type=_TS,
        requirement=Requirement.REQUIRED_FOR_REPLAY,
        summary="The instant this row first became visible IN YOUR SYSTEM -- distinct from when the trip happened, and distinct from when the extract was run.",
        unlocks="Reconstructing what your system knew at any chosen instant, which is the precondition for judging a decision against the information available when it was made rather than against hindsight.",
        lost_without_it="We would use OUR receipt time as a proxy for YOUR knowledge time. If your system knew at 10:30 and exported at 11:00, our 10:45 reconstruction excludes it -- correct for us, but your dispatcher knew. Replay would then systematically credit your staff with LESS information than they had, and bias every comparison in our favour. We refuse to publish a comparison built that way, so without this field decision replay is withdrawn rather than degraded.",
        operator_question="Does every record carry a creation/entry timestamp written by your system when the row first appeared -- and is it exportable? Many systems do not have one, and that is a valid answer.",
        note="This cannot be retrofitted. History already exported without it stays without it, which is why it is asked before the first extract rather than after.",
    ),
    FieldSpec(
        name="record_updated_known_at",
        shape=Shape.COLUMN,
        value_type=_TS,
        requirement=Requirement.REQUIRED_FOR_REPLAY,
        summary="When the row was last changed in your system.",
        unlocks="Replaying revisions, not just arrivals -- a trip cancelled at 09:10 was on the board until 09:10 and off it afterwards.",
        lost_without_it="Only the final state of each trip is reconstructable. A day's board can be rebuilt from bookings that arrived, but not from the cancellations, re-times and reassignments that changed it during the day -- which is most of what a dispatcher actually reacts to.",
        operator_question="Does the record carry a last-modified timestamp? Better still: can you export a change log with one row per change rather than one row per trip?",
        note="A change log is the ideal and a created/modified pair is the cheap approximation. If you can only give one, give created.",
    ),
    FieldSpec(
        name="knowledge_time_source",
        shape=Shape.DECLARATION,
        value_type="a system name, plus what writes the timestamp",
        requirement=Requirement.REQUIRED_FOR_REPLAY,
        conditional_on="record_created_known_at is supplied",
        summary="Which system stamps the creation timestamp, and whether it is the operational system or the reporting/export layer.",
        unlocks="Knowing that the knowledge timestamp is real. A created_at written by a data warehouse load or by the export tool is the export time wearing a disguise, and it is indistinguishable from the real thing by inspection alone.",
        lost_without_it="We would treat an ETL load time as the dispatcher's knowledge time. That is worse than having no knowledge timestamp, because the resulting replay looks rigorous and is wrong in a direction we cannot see.",
        operator_question="What writes that timestamp -- the booking/dispatch application at the moment of entry, or a downstream warehouse/report layer when the row was copied?",
    ),
    # -- HELPFUL ---------------------------------------------------------------
    FieldSpec(
        name="actual_dropoff_at",
        shape=Shape.COLUMN,
        value_type=_TS,
        requirement=Requirement.HELPFUL,
        summary="When the trip actually finished.",
        unlocks="Deadhead as a MEASUREMENT. The empty leg runs from one trip's dropoff to the next trip's pickup, and this is its start.",
        lost_without_it="Deadhead can only be bounded, not measured: pickup-to-pickup includes the in-service time, so every figure is an upper bound. We would report it as a bound and label it as one, which is a materially weaker statement.",
        operator_question="Is an actual dropoff/completion time recorded and exportable for served trips?",
    ),
    FieldSpec(
        name="scheduled_dropoff_at",
        shape=Shape.COLUMN,
        value_type=_TS,
        requirement=Requirement.HELPFUL,
        summary="The promised or scheduled dropoff time.",
        unlocks="The dropoff half of the promise, and a check on maximum-ride-time constraints -- one of the reasons a trip is refused.",
        lost_without_it="A trip that was picked up on time and delivered an hour late reads as on time. Ride-time constraint violations are invisible.",
        operator_question="Is a scheduled or promised dropoff/appointment time exported?",
    ),
    FieldSpec(
        name="outcome_known_at",
        shape=Shape.COLUMN,
        value_type=_TS,
        requirement=Requirement.HELPFUL,
        summary="When you learned the outcome -- particularly when a cancellation was received.",
        unlocks="Separating a cancellation received at 06:00, where the slot was recoverable, from one received at 08:14 when the vehicle was already en route. That difference is the entire operational content of a cancellation.",
        lost_without_it="All cancellations look alike, and the recoverable ones cannot be counted. Late-notice no-shows and early cancellations collapse into one rate.",
        operator_question="Is the time a cancellation or no-show was recorded kept separately from the trip's scheduled time?",
        note="If record_updated_known_at is supplied and maintained, this is largely implied by it. Sent separately it is more reliable, because it is the one timestamp a dispatcher enters deliberately.",
    ),
    FieldSpec(
        name="denial_code",
        shape=Shape.COLUMN,
        value_type="your own code, verbatim -- do NOT map it onto our vocabulary",
        requirement=Requirement.HELPFUL,
        summary="Why a trip was refused, in your system's own code.",
        unlocks="Telling capacity denials apart from policy denials. 'No accessible vehicle was free' is an operational finding; 'outside the service area' is a policy statement about the boundary, and conflating them makes the first one disappear into the second.",
        lost_without_it="`denied` is one undifferentiated bucket. We can count denials and can say nothing about them.",
        operator_question="Does a denial or refusal carry a reason code? Send the code as it appears -- our own reason vocabulary is ours, not yours, and we will map yours to it explicitly and publish the mapping.",
    ),
    FieldSpec(
        name="denial_code_list",
        shape=Shape.DECLARATION,
        value_type="the code list, with each code's meaning in your words",
        requirement=Requirement.REQUIRED,
        conditional_on="the export contains any denied rows",
        summary="What your denial codes mean.",
        unlocks="Mapping your vocabulary onto ours by agreement rather than by resemblance.",
        lost_without_it="Codes get bucketed by how they look, which is a fabrication dressed as a mapping. We would rather leave them unmapped and report them verbatim.",
        operator_question="Can you send the denial/refusal code list with a one-line meaning per code? Expect a long tail and expect one code to mean 'other' -- tell us which one.",
        note="Required only because an export containing denied rows and no code list forces exactly the guess this contract exists to prevent. If there are no denied rows, this line does not apply.",
    ),
    FieldSpec(
        name="trip_distance",
        shape=Shape.COLUMN,
        value_type="number, miles",
        requirement=Requirement.HELPFUL,
        summary="Distance travelled in service for the trip, as your system records it.",
        unlocks="Reporting deadhead in the same unit your NTD submission uses, so the figure can be checked against a number you already file rather than against one only we can compute.",
        lost_without_it="Deadhead is reported in minutes only. That is still a real measurement, but it is not directly comparable to your own reporting, and a figure nobody can cross-check is a figure nobody acts on.",
        operator_question="Is per-trip in-service mileage recorded, and is it measured (odometer/AVL) or estimated by the scheduler?",
    ),
    FieldSpec(
        name="run_roster",
        shape=Shape.TABLE,
        value_type="one row per run per day: run_ref, vehicle_ref, run_start_at, run_end_at, securement_positions",
        requirement=Requirement.HELPFUL,
        summary="Which runs operated on each day, on which vehicle, between which times, with how many wheelchair securement positions.",
        unlocks="Knowing what the fleet actually was. Any 'a different assignment would have been better' statement needs the set of vehicles that existed and were on shift; and a denial for no accessible capacity can only be checked against the accessible vehicles that were actually free.",
        lost_without_it="A counterfactual can only re-sequence trips inside the runs that happened. It cannot say a different vehicle should have taken a trip, because it does not know which vehicles existed. Accessibility denials can be counted but not tested -- so we would report the count and refuse the conclusion.",
        operator_question="Can you send a run roster for the same period: run id, vehicle, start and end time, and the number of wheelchair securement positions on that vehicle? Are securement positions fixed per vehicle, or reconfigurable during a day?",
        note="This asks about VEHICLES, not riders. Nothing in it describes a person, and no rider mobility-device or eligibility field is requested anywhere in this contract.",
    ),
    FieldSpec(
        name="candidate_log",
        shape=Shape.TABLE,
        value_type="one row per rejected candidate: trip_ref, candidate_vehicle_ref or candidate_run_ref, rejection code, evaluated_at",
        requirement=Requirement.HELPFUL,
        conditional_on="alternatives_logged = yes",
        summary="The assignments your scheduler considered and rejected.",
        unlocks="Comparing against what your system actually weighed, rather than against a set of options we reconstruct and then grade ourselves on.",
        lost_without_it="Any comparison is between your decision and our reconstruction of the option set. That is a weaker claim, and we would label it as one rather than presenting it as a replay.",
        operator_question="If your scheduler logs rejected candidates, can those logs be exported for the same period?",
    ),
    FieldSpec(
        name="field_authority_map",
        shape=Shape.DECLARATION,
        value_type="per field: which named system is authoritative",
        requirement=Requirement.HELPFUL,
        conditional_on="source_systems names more than one system",
        summary="When two of your systems disagree about a field, which one is right.",
        unlocks="A precedence rule for conflicts. Our model retains both values and refuses to choose; this is the answer that lets it choose.",
        lost_without_it="Disagreements stay unresolved and are reported as conflicts rather than as values. Nothing is corrupted, but a number is missing where a number was expected, and it stops the analysis rather than biasing it.",
        operator_question="If the AVL feed and the dispatch console disagree about an actual pickup time, which is authoritative? Does the answer differ by shift, by contractor, or by field?",
        note="'It depends' is the expected answer and is worth writing down as-is. A precedence rule with an honest exception list beats a clean one that nobody in dispatch believes.",
    ),
)


# ---------------------------------------------------------------------------
# What we are deliberately NOT asking for
# ---------------------------------------------------------------------------

NOT_REQUESTED: tuple[NotRequested, ...] = (
    NotRequested(
        name="rider_ref (any rider identifier, including one you have already hashed)",
        why_not=(
            "Nothing in the analysis described here needs to link two trips to the "
            "same person. The adapter still accepts and tokenises the column "
            "because ADR-0038 shipped it as optional, but this contract does not "
            "ask for it, and the tokenisation is an unsalted hash -- a pseudonym, "
            "not anonymisation, and brute-forceable by anyone holding your client "
            "list."
        ),
        what_we_give_up=(
            "Repeat-rider behaviour: no-show propensity, whether the same people "
            "are late repeatedly, subscription-trip patterns. All of it."
        ),
        when_we_would_ask=(
            "Only if rider-level no-show behaviour became the agreed question, and "
            "only with a salted pseudonym generated on your side and a separate "
            "written basis for it. Not for the evaluation this contract covers."
        ),
    ),
    NotRequested(
        name="driver or operator identifier, even tokenised",
        why_not=(
            "Everything we compute attributes work to a RUN, not to a person. A "
            "driver id would buy nothing and would add a person to a dataset that "
            "otherwise contains none. Shift boundaries -- the one thing a driver id "
            "might have been used for -- are asked for on the run roster instead."
        ),
        what_we_give_up=(
            "Any per-driver variation: whether lateness clusters by operator. That "
            "is a performance-management question, and it is not one we are "
            "offering to answer."
        ),
        when_we_would_ask="Not currently foreseen.",
    ),
    NotRequested(
        name="rider mobility-device, eligibility category, or trip purpose",
        why_not=(
            "These are health-adjacent facts about an individual. ADR-0038 refuses "
            "them and this contract does not reopen that."
        ),
        what_we_give_up=(
            "This is the one omission that costs something real and it should be "
            "said plainly. Without a per-trip flag for whether an accessible "
            "vehicle was required, we can count denials coded as accessibility "
            "denials and check them against the accessible vehicles on shift (via "
            "the run roster), but we cannot measure unmet ACCESSIBLE demand "
            "directly -- only the subset your own system already labelled."
        ),
        when_we_would_ask=(
            "If accessibility-denial analysis becomes the agreed question, this is "
            "the field that would make it possible, and it is a decision for your "
            "counsel rather than a request we will make by default. We are raising "
            "it here so the trade-off is visible, not to ask for it."
        ),
    ),
    NotRequested(
        name="fare, payment, funding source, subscription status",
        why_not="No capability in this contract consumes them.",
        what_we_give_up="Any cost or revenue statement, which we are not making.",
        when_we_would_ask=(
            "A cost-per-hour split (fixed versus variable) would be needed before "
            "any monetary figure could be quoted at all, and that is a separate "
            "conversation with a separate refusal attached: we do not quote a "
            "saving from a deadhead figure."
        ),
    ),
    NotRequested(
        name="GPS breadcrumb traces / raw AVL position streams",
        why_not=(
            "A breadcrumb trail is a doorstep whenever the vehicle is stopped. "
            "Zones plus timestamps answer the questions in this contract without "
            "carrying precise location."
        ),
        what_we_give_up="Route-level deadhead geometry and true empty mileage.",
        when_we_would_ask=(
            "A per-trip odometer delta (trip_distance, above) answers the mileage "
            "question without a trace, so we ask for that instead."
        ),
    ),
    NotRequested(
        name="free-text notes, driver comments, dispatcher remarks",
        why_not=(
            "This is where personal detail actually hides, and we cannot review "
            "your free text for you. It is refused, not merely unrequested."
        ),
        what_we_give_up="Whatever context a dispatcher wrote down. Genuinely a loss; taken anyway.",
        when_we_would_ask="Never in this form.",
    ),
    NotRequested(
        name="live API access, database credentials, or a system integration",
        why_not=(
            "A file is all we want at this stage. An integration is a much larger "
            "commitment on your side and answers nothing this contract does not."
        ),
        what_we_give_up="Nothing, for the evaluation described here.",
        when_we_would_ask="Not at evaluation stage.",
    ),
)


REFUSALS: tuple[Refusal, ...] = (
    Refusal(
        category="Personal names -- riders, carers, emergency contacts, or your own staff",
        example_columns=("rider_name", "client_name", "first_name", "last_name", "driver_name"),
        why="Direct identifier. Nothing we compute uses a name.",
    ),
    Refusal(
        category="Email addresses",
        example_columns=("email", "rider_email", "contact_email"),
        why="Direct identifier, and the one that survives a column rename -- so it is also checked by value, in every cell.",
    ),
    Refusal(
        category="Phone numbers",
        example_columns=("phone", "home_phone", "mobile", "cell", "fax"),
        why="Direct identifier.",
    ),
    Refusal(
        category="Street addresses",
        example_columns=("pickup_address", "dropoff_address", "home_address", "street", "addr1", "apt"),
        why="A pickup address is a rider's home. Zones exist precisely so this column does not have to travel.",
    ),
    Refusal(
        category="National, insurance or medical identifiers",
        example_columns=("ssn", "national_id", "nhs_number", "medicaid_id", "medicare_id", "insurance_id", "mrn"),
        why="Direct identifier, and in most jurisdictions a special category on top of that.",
    ),
    Refusal(
        category="Dates of birth",
        example_columns=("dob", "date_of_birth", "birth_date"),
        why="Quasi-identifier strong enough to re-identify on its own in combination with a zone.",
    ),
    Refusal(
        category="Medical or eligibility detail",
        example_columns=("diagnosis", "disability_type", "medical_condition", "eligibility_category"),
        why="Health data about an individual. Refused regardless of any consent you may hold.",
    ),
    Refusal(
        category="Free text of any kind",
        example_columns=("notes", "comments", "remarks", "driver_notes"),
        why="Unreviewable. Personal detail hides here more reliably than in the columns that announce themselves.",
    ),
    Refusal(
        category="Driver-licensing and vehicle-registration identifiers",
        example_columns=("driver_license", "hack_license", "medallion", "license_plate", "vin"),
        why=(
            "A hack licence is a person's licence, not a vehicle's, and licensee "
            "lookups are public. The 2013 NYC TLC release hashed medallion and hack "
            "licence and was de-anonymised within days because the input space is "
            "enumerable. A plate or VIN is registered to a person or a company and "
            "resolves through public and commercial lookups."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Prose. Hand-written, rendered into the companion document verbatim so the two
# artifacts cannot drift and the human one still reads like a document rather
# than a table dump.
# ---------------------------------------------------------------------------

HONESTY_STATEMENT = """\
**Milexium has no operator customers, no pilot, and no operator data of any
kind.** Every capability described here is Demonstrated on public and
open-standard data and on a deliberately fictional reference agency. Nothing is
Validated, which in our own status vocabulary means "tested on consented
operator data against a declared baseline". You would be the first, and this
document exists because being first should mean being told exactly what is being
asked for and why, not being handed a data request with no reasoning attached.

**This is not an agreement and cannot create one.** The data-sharing agreement --
parties, jurisdiction, liability, breach notification, termination -- is a legal
instrument for counsel on both sides. This is the technical schedule such an
agreement would reference. Sending a file does not accept terms, because there
are no terms here to accept.
"""

THE_ASK_TEMPLATE = """\
The whole request, in one paragraph:

**{columns} columns you already export, {questions} questions answerable in an
email, and {replay} timestamps that decide whether half of this is worth doing at
all.** The {columns} columns are unchanged from what we have published since
ADR-0038 -- this document adds no new mandatory column, and `vehicle_ref` /
`run_ref` are an either-or, so in practice it is {columns_in_practice} columns in
the file. The {questions} questions cost you one reply. The {replay} timestamps
are the part that cannot be added later, and the reason this document exists at
all.
"""
"""Counts are substituted from the field list rather than typed, so the headline
number cannot drift away from the table underneath it. A document that opens with
"eight columns" over a list of eleven is the cheapest way to lose an operator's
confidence, and it happens by editing the list and not the sentence."""

WHY_KNOWLEDGE_TIME = """\
This is the section to read if you read only one.

When we reconstruct a decision, we need to know what your system knew at the
moment it was made. Today we would use **our** receipt time as a stand-in for
**your** knowledge time. Consider what that does:

> Your system learns at 10:30 that a vehicle is out of service. The extract runs
> at 11:00. We reconstruct the 10:45 board, and the vehicle is still on it --
> because as far as our clock is concerned, we did not know until 11:00.
>
> **But your dispatcher knew at 10:30.**

Every reconstruction built that way credits your staff with *less* information
than they actually had. And the bias has a direction: it makes your decisions
look worse than they were, and therefore makes any "an alternative assignment
would have done better" comparison look better than it is -- **in our favour**.

We are not willing to publish a comparison built on that. So the ask is a
per-row timestamp recording when the record became visible **in your system**,
distinct from when the trip happened and distinct from when the extract ran.

Two things follow, and both are uncomfortable enough to be worth stating:

1. **Many systems do not record one.** That is a completely valid answer, and it
   is the answer we most need to have before data moves, not after. If the
   answer is no, the export is still worth sending -- outcome analysis, deadhead
   measurement and demand work are all unaffected -- and decision replay is
   withdrawn from what we claim, rather than quietly approximated.
2. **It cannot be retrofitted.** A history exported without it stays without it
   forever. Adding the column next year does not repair last year.

**And a related warning about backfill.** Eight to twelve weeks arriving as a
single extract gives every row the same arrival time from our side, so every
reconstruction across that whole history shares one boundary and the
point-in-time property collapses to nothing. Without a source-side knowledge
timestamp, **backfilled data supports outcome analysis but not decision
replay.** Our validator detects exactly this and says so, rather than reporting
a capability we cannot actually deliver.
"""

MINIMUM_VIABLE_ASK = """\
**Eight to twelve weeks, from one agency, complete over that window.**

Not five years. Not five agencies. One complete decision-to-outcome chain --
bookings arriving, assignments made, outcomes recorded, over a period long
enough to contain a holiday, a bad-weather day and a normal Tuesday -- is worth
more than five years of disconnected trip totals, because trip totals answer
"what happened" and a chain answers "what was knowable when the choice was
made". Only the second one supports anything a scheduler could act on.

Three things matter more than volume:

- **Complete over the window, not filtered.** Include denied, cancelled and
  no-show trips, the contracted-out work, and the days you would rather not show
  us. An export of served trips only makes unmet demand structurally invisible,
  and a forecast trained on it learns the shape of what you were able to serve
  rather than the shape of what was asked for. A validator finding of "every row
  in this sample has outcome=served" is treated as a defect in the extract, not
  as a perfect service record.
- **A small sample first.** Two hundred rows, fully representative, tells us and
  you far more than a full extract, because it lets both sides find the problems
  before anything of size moves. Run the validator on it -- it is the fastest way
  to turn this document into a short, specific conversation.
- **Eight weeks is a floor, not a target.** Below it, day-of-week and weather
  effects are not separable from noise, and we would be reporting the sample.
"""

VALIDATOR_NOTE = """\
`talos/contracts/validate_operator_export.py` reads a sample export and reports,
capability by capability, what it can and cannot support -- naming the missing
field in each case. It writes nothing, sends nothing, and needs no network.

```
py -3 talos/contracts/validate_operator_export.py sample.csv
```

A typical answer looks like this, and this is the sentence this whole document
is built to make possible:

> This export supports outcome analysis and deadhead measurement. It cannot
> support decision replay, because no source-side knowledge timestamp is
> present.

It also checks the failure that a presence check would miss: a knowledge
timestamp that is **present and degenerate** -- identical on every row, or equal
to the export time, which is the signature of a value stamped by the extract
rather than recorded by the operational system. A column that looks right and
means nothing is worse than an absent one, because the resulting analysis looks
rigorous.

You are welcome to run it yourself, before anything leaves your building.
"""

PSEUDONYMISATION_STATEMENT = """\
**Rider identity must never arrive in the clear, and the gate runs before
everything else.** PII is checked ahead of all other validation -- ahead of
required-field checks, ahead of timestamp parsing, ahead of any repair of a
malformed value. A row that is both malformed and carries a rider name is
rejected on the identity ground, and the offending value is redacted from the
rejection record itself, so a rejection for rider PII never becomes a file full
of rider PII (ADR-0051).

**What we refuse to accept**, whether or not it is encrypted, zipped, or sent
"just in case it is useful": every category in the refusals table below. Refusal
means the export is set aside and you are asked to re-cut it -- not imported with
the column ignored. A column carrying a direct identifier stops the row even when
that column is blank in the sample you sent, because an all-blank column in a
two-hundred-row sample is usually a populated column in the full extract.

**An identifier does not have to be called a name to be one.** In an
owner-operator fleet -- one vehicle, one driver, one licensee -- a vehicle number
*is* a pseudonymous person identifier. `vehicle_ref` is safe for an agency's
numbered bus and unsafe for a single-vehicle subcontractor, and **nothing about
the column tells you which**. That is why the fleet-shape question is asked
directly and answered by you, rather than inferred by us from a header (ADR-0057).
If any vehicle in your export is operated by exactly one person, tokenise
`vehicle_ref` on your side before export, or send `run_ref` instead.

**Minimisation is structural, not a policy someone remembers.** Columns outside
this contract are recorded **by name only, never by value** -- an unrecognised
column in an operator export is precisely where unanticipated personal data
hides, so we decline to keep what is in it while still recording that it
existed, because silently dropping a column is its own kind of dishonesty.

**Where pseudonymisation is weak, we say so rather than implying strength.** If a
rider identifier is sent despite this document asking you not to send one, it is
replaced by an unsalted SHA-256 truncated to 24 hex characters. That is a
pseudonym, not anonymisation: over a small identifier space it is reversible by
brute force by anyone who already holds your client list, and it does not by
itself take the field outside your privacy obligations. This is stated as a
reason to omit the column, not as a reassurance.

**Honest limit on all of the above.** The automated checks are a backstop, not a
guarantee. They catch columns that announce themselves, email addresses that look
like email addresses, and zone values shaped like street addresses. A rider's
name in a column called `ref2` is not caught by anything. **This document is the
contract; the code is the seatbelt.** If you are unsure about a column, ask
before exporting rather than sending it.
"""

LIMITATIONS = (
    "This is a contract, not an integration. Nothing here connects to any "
    "scheduling system, and no operator has confirmed that any field in it "
    "exists in the shape described. Every field is a request, and several are "
    "requests we expect to be answered 'we do not record that'.",
    "The field list is derived from what this repository can currently consume "
    "and from what ADR-0072 had to guess about operator data. It is not derived "
    "from any real vendor export, because none has been seen.",
    "The validator reads a sample and reports on the sample. A sample that is "
    "clean is not evidence that the full extract is, and a column populated in "
    "two hundred rows may be null in the other two million.",
    "Requirement levels are our judgement about what makes a claim defensible. "
    "An operator may reasonably disagree about which fields are worth the effort, "
    "and that disagreement is a conversation this document is meant to start, "
    "not a rule it is meant to impose.",
    "No capability listed here has ever been exercised on operator data. Each "
    "one describes what the code in this repository is built to do, on the data "
    "described. None is a track record.",
)


# ---------------------------------------------------------------------------
# Derived views. Everything below is computed from the declarations above, so
# there is one list and not several that can disagree.
# ---------------------------------------------------------------------------

FIELDS_BY_NAME: dict[str, FieldSpec] = {spec.name: spec for spec in FIELDS}
CAPABILITIES_BY_ID: dict[str, Capability] = {cap.id: cap for cap in CAPABILITIES}


def fields_with(requirement: Requirement) -> tuple[FieldSpec, ...]:
    return tuple(spec for spec in FIELDS if spec.requirement is requirement)


def required_columns() -> tuple[str, ...]:
    """The mandatory trip-export columns. Asserted against
    `themis.connect.operator_export.REQUIRED_COLUMNS` by conformance test, so
    the contract cannot promise an operator something the adapter does not
    enforce -- or ask for something the adapter would reject."""
    return tuple(
        spec.name
        for spec in FIELDS
        if spec.requirement is Requirement.REQUIRED and spec.shape is Shape.COLUMN
    )


def required_declarations(*, conditional: bool = False) -> tuple[FieldSpec, ...]:
    """The questions an operator answers by email. `conditional=False` returns
    the ones that always apply -- the set the companion document counts."""
    return tuple(
        spec
        for spec in FIELDS
        if spec.shape is Shape.DECLARATION
        and spec.requirement is Requirement.REQUIRED
        and (spec.conditional_on is not None) is conditional
    )


_NUMBER_WORDS = (
    "zero", "one", "two", "three", "four", "five",
    "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
)


def _spell(count: int) -> str:
    """Small numbers read as words in prose. Purely cosmetic; the value is still
    derived from the field list, so it cannot disagree with the table."""
    return _NUMBER_WORDS[count] if count < len(_NUMBER_WORDS) else str(count)


def the_ask() -> str:
    """The headline paragraph, with every number computed from the field list."""
    columns = required_columns()
    either_or = tuple(
        spec.name
        for spec in FIELDS
        if spec.conditional_on == "at least one of vehicle_ref / run_ref"
    )
    return THE_ASK_TEMPLATE.format(
        columns=_spell(len(columns)),
        columns_in_practice=_spell(
            len(columns) - (len(either_or) - 1 if either_or else 0)
        ),
        questions=_spell(len(required_declarations())),
        replay=_spell(
            len(
                [
                    spec
                    for spec in fields_with(Requirement.REQUIRED_FOR_REPLAY)
                    if spec.shape is Shape.COLUMN
                ]
            )
        ),
    )


def capabilities_needing(field_name: str) -> tuple[str, ...]:
    """Which capabilities the field gates. A field gating nothing is a field
    that should not be in the contract, and a test asserts none exists."""
    out = []
    for cap in CAPABILITIES:
        if field_name in cap.requires or field_name in cap.requires_any or field_name in cap.sharpened_by:
            out.append(cap.id)
    return tuple(out)


_REQUIREMENT_MEANING: dict[Requirement, str] = {
    Requirement.REQUIRED: (
        "For a column: absent -> we decline the export rather than produce a "
        "number we cannot defend. This set is identical to the one already "
        "published in "
        + INTAKE_DOCUMENT
        + "; this contract adds no new mandatory column. For a declaration: "
        "unanswered -> we do not start, because each answer changes how the file "
        "must be read. Each is one line of an email, and 'we do not record that' "
        "is an acceptable answer to every one of them."
    ),
    Requirement.REQUIRED_FOR_REPLAY: (
        "Absent -> the export is still worth sending and outcome analysis is "
        "unaffected, but decision replay and any counterfactual comparison are "
        "WITHDRAWN, not approximated. Cannot be retrofitted onto history already "
        "exported without it."
    ),
    Requirement.HELPFUL: (
        "Absent -> one named capability is narrowed in a way we can state "
        "precisely. Nothing else is affected."
    ),
}


def as_dict() -> dict:
    """The machine-readable contract. Deterministic: no clock, no environment,
    no iteration over a set. The drift gate compares bytes."""
    return {
        "contract_id": CONTRACT_ID,
        "contract_version": CONTRACT_VERSION,
        "contract_date": CONTRACT_DATE,
        "generated_by": "talos/contracts/generate.py from talos/contracts/operator_contract.py",
        "note": "Generated. Do not hand-edit -- change operator_contract.py and regenerate.",
        "status": {
            "operator_data_held": "none",
            "pilots": "none",
            "validated_claims": "none",
            "status_vocabulary": "forge/knowledge/architecture/decisions/0001-adopt-expansion-blueprint-and-control-plane.md",
            "statement": (
                "Milexium holds no operator data. Nothing in this contract has been "
                "exercised on an operator export. Every capability listed is what the "
                "code is built to do, not something it has been shown to do on real data."
            ),
        },
        "related": {
            "intake_document": INTAKE_DOCUMENT,
            "intake_adapter": INTAKE_ADAPTER,
            "companion_document": "talos/contracts/OPERATOR_DATA_CONTRACT.md",
            "validator": "talos/contracts/validate_operator_export.py",
        },
        "answer_options": list(ANSWER_OPTIONS),
        "minimum_viable_ask": {
            "weeks": [8, 12],
            "agencies": 1,
            "must_be_complete_over_window": True,
            "must_include_non_served_outcomes": True,
            "statement": (
                "Eight to twelve weeks from one agency, complete over that window. "
                "One complete decision-to-outcome chain is worth more than five years "
                "of disconnected trip totals."
            ),
        },
        "requirement_levels": {
            level.value: _REQUIREMENT_MEANING[level] for level in Requirement
        },
        "capabilities": [
            {
                "id": cap.id,
                "name": cap.name,
                "question_it_answers": cap.question_it_answers,
                "requires": list(cap.requires),
                "requires_any": list(cap.requires_any),
                "sharpened_by": list(cap.sharpened_by),
            }
            for cap in CAPABILITIES
        ],
        "fields": [
            {
                "name": spec.name,
                "shape": spec.shape.value,
                "value_type": spec.value_type,
                "requirement": spec.requirement.value,
                "conditional_on": spec.conditional_on,
                "summary": spec.summary,
                "unlocks": spec.unlocks,
                "lost_without_it": spec.lost_without_it,
                "operator_question": spec.operator_question,
                "gates_capabilities": list(capabilities_needing(spec.name)),
                "note": spec.note,
            }
            for spec in FIELDS
        ],
        "not_requested": [
            {
                "name": item.name,
                "why_not": item.why_not,
                "what_we_give_up": item.what_we_give_up,
                "when_we_would_ask": item.when_we_would_ask,
            }
            for item in NOT_REQUESTED
        ],
        "refused": [
            {
                "category": item.category,
                "example_columns": list(item.example_columns),
                "why": item.why,
            }
            for item in REFUSALS
        ],
        "pseudonymisation_and_minimisation": PSEUDONYMISATION_STATEMENT,
        "limitations": list(LIMITATIONS),
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def _field_table(specs: tuple[FieldSpec, ...]) -> list[str]:
    lines = [
        "| Field | Where | Type | What it is |",
        "|---|---|---|---|",
    ]
    for spec in specs:
        name = f"`{spec.name}`"
        if spec.conditional_on:
            name += f"<br>*({spec.conditional_on})*"
        lines.append(
            f"| {name} | {spec.shape.value} | {spec.value_type} | {spec.summary} |"
        )
    return lines


def _field_detail(spec: FieldSpec) -> list[str]:
    lines = [f"#### `{spec.name}`", ""]
    if spec.conditional_on:
        lines.append(f"*Applies when: {spec.conditional_on}.*")
        lines.append("")
    lines.append(f"**What it is.** {spec.summary}")
    lines.append("")
    lines.append(f"**What it unlocks.** {spec.unlocks}")
    lines.append("")
    lines.append(f"**What is lost without it.** {spec.lost_without_it}")
    lines.append("")
    lines.append(f"**The question to answer.** {spec.operator_question}")
    if spec.note:
        lines.append("")
        lines.append(f"**Note.** {spec.note}")
    lines.append("")
    return lines


def as_markdown() -> str:
    """The companion document. An operations director should be able to read it
    end to end without a schema; the field detail is at the back for whoever
    actually runs the extract."""
    out: list[str] = []
    add = out.append

    add("# The operator data contract — what we need, and what each field buys")
    add("")
    add(
        f"**Version {CONTRACT_VERSION} — {CONTRACT_DATE}.** Generated from"
        " `talos/contracts/operator_contract.py`; if this document and that module"
        " disagree, the module is what runs and this document is the bug."
    )
    add("")
    add(
        "**For:** the operations director who would approve the extract, the IT lead"
        " who would run it, and the counsel who would review it. The first three"
        " sections need no schema knowledge. The field detail at the back is for"
        " whoever writes the query."
    )
    add("")
    add("---")
    add("")
    add("## 0. Read this first")
    add("")
    add(HONESTY_STATEMENT)
    add("---")
    add("")
    add("## 1. The ask")
    add("")
    add(the_ask())
    add("---")
    add("")
    declarations = required_declarations()
    add(f"## 2. The {_spell(len(declarations))} questions")
    add("")
    add(
        "These cost you one email and they decide more than the data does. Every one"
        " of them can be answered **yes**, **no**, or **we do not record that** — and"
        ' "we do not record that" is a useful answer, not a failure. It tells us what'
        " we may never claim."
    )
    add("")
    for index, spec in enumerate(declarations, start=1):
        add(f"**{index}. {spec.operator_question}**")
        add("")
        add(f"> *Why:* {spec.unlocks}")
        add(">")
        add(f"> *If we do not know:* {spec.lost_without_it}")
        add("")
    for spec in required_declarations(conditional=True):
        add(f"**And one more, but only if {spec.conditional_on}.**")
        add("")
        add(f"{spec.operator_question}")
        add("")
        add(f"> *Why:* {spec.unlocks}")
        add(">")
        add(f"> *If we do not know:* {spec.lost_without_it}")
        add("")
    add("---")
    add("")
    add("## 3. The two timestamps, and why they decide half of this")
    add("")
    add(WHY_KNOWLEDGE_TIME)
    add("---")
    add("")
    add("## 4. What we can answer, and what each answer costs")
    add("")
    add(
        "Every field in this document exists because it moves one of these from"
        ' "we cannot answer that" to "we can". A field that does not appear in this'
        " table has no business being in the contract."
    )
    add("")
    add("| We could answer | Which needs |")
    add("|---|---|")
    for cap in CAPABILITIES:
        needs = list(cap.requires)
        if cap.requires_any:
            needs.append("one of " + " / ".join(cap.requires_any))
        rendered = ", ".join(f"`{item}`" for item in needs)
        if cap.sharpened_by:
            sharp = ", ".join(f"`{item}`" for item in cap.sharpened_by)
            rendered += f"<br>*sharpened by* {sharp}"
        add(f"| **{cap.name}** — {cap.question_it_answers} | {rendered} |")
    add("")
    add("---")
    add("")
    add("## 5. The fields")
    add("")
    for level in (Requirement.REQUIRED, Requirement.REQUIRED_FOR_REPLAY, Requirement.HELPFUL):
        specs = fields_with(level)
        if not specs:
            continue
        heading = {
            Requirement.REQUIRED: "Required",
            Requirement.REQUIRED_FOR_REPLAY: "Required for decision replay",
            Requirement.HELPFUL: "Helpful",
        }[level]
        add(f"### {heading}")
        add("")
        add(_REQUIREMENT_MEANING[level])
        add("")
        out.extend(_field_table(specs))
        add("")
    add("---")
    add("")
    add("## 6. What we are NOT asking for, and why")
    add("")
    add(
        "A field list without this section reads as *send everything you have*,"
        " whatever the header says. Each of the following exists in your system, and"
        " each is deliberately left out."
    )
    add("")
    for item in NOT_REQUESTED:
        add(f"**{item.name}**")
        add("")
        add(f"- *Why not:* {item.why_not}")
        add(f"- *What we give up:* {item.what_we_give_up}")
        add(f"- *When we would ask:* {item.when_we_would_ask}")
        add("")
    add("---")
    add("")
    add("## 7. Pseudonymisation and minimisation — what we will refuse to accept")
    add("")
    add(PSEUDONYMISATION_STATEMENT)
    add("### The refusals, by category")
    add("")
    add("| We will not accept | Column names we see | Why |")
    add("|---|---|---|")
    for refusal in REFUSALS:
        columns = ", ".join(f"`{name}`" for name in refusal.example_columns)
        add(f"| {refusal.category} | {columns} | {refusal.why} |")
    add("")
    add("---")
    add("")
    add("## 8. The minimum viable ask")
    add("")
    add(MINIMUM_VIABLE_ASK)
    add("---")
    add("")
    add("## 9. Check your own export before sending it")
    add("")
    add(VALIDATOR_NOTE)
    add("---")
    add("")
    add("## 10. Limitations of this document")
    add("")
    for limitation in LIMITATIONS:
        add(f"- {limitation}")
    add("")
    add("---")
    add("")
    add("## 11. The field detail")
    add("")
    add(
        "For whoever writes the extract. One entry per field, in the order of the"
        " table in §5."
    )
    add("")
    for level in (Requirement.REQUIRED, Requirement.REQUIRED_FOR_REPLAY, Requirement.HELPFUL):
        for spec in fields_with(level):
            out.extend(_field_detail(spec))
    return "\n".join(out).rstrip() + "\n"
