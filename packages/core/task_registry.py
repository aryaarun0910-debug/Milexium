"""Task registry (Program D contract, v0.1 first slice).

A small, closed vocabulary of task names this repository has a real model
for -- not the full task list `blueprint/05-core-model-runtime-and-forecast.md`
sketches for Program D (that list includes tasks such as
`forecast.trip_duration` or `forecast.no_show` with no implementation here;
adding them stays Specified until a real model exists). Task names follow
that same blueprint's dotted vocabulary so a future implementation of the
rest of Program D does not have to rename what this slice already registered.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class UnknownTaskError(ValueError):
    """Raised when a task name is not in the closed `TASK_REGISTRY` vocabulary."""


class TaskDescriptor(BaseModel):
    """What a task means and how to read `ModelVersion.feature_schema_version`
    for it. Deliberately does not enumerate valid schema version strings --
    that stays an opaque, model-registry-assigned label (see `ModelRegistry`
    docstring) rather than a second closed vocabulary to keep in sync."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task: str
    description: str
    feature_schema_convention: str


TASK_REGISTRY: dict[str, TaskDescriptor] = {
    "forecast.demand": TaskDescriptor(
        task="forecast.demand",
        description=(
            "Forecast trip demand for a zone (or an agency) one step ahead, "
            "day-ahead for hourly zone grains or month-ahead for the agency "
            "monthly grain, from historical demand, calendar, and (for the "
            "hourly grains) weather features. Real implementations in this "
            "repository (docs/MODEL_CARDS.md): NYC Access-A-Ride paratransit "
            "bookings per borough-hour (the product target), Chicago TNP "
            "trips per community-area-hour, MTA bus AFC ridership per "
            "route-hour, MTA subway AFC ridership per station-hour, and "
            "nationwide NTD demand-response ridership per agency-month."
        ),
        feature_schema_convention=(
            "`ModelVersion.feature_schema_version` is an opaque label "
            "identifying the exact feature set and spatial/temporal grain a "
            "given model version was trained on -- not a version number on a "
            "single shared schema, because this task covers two distinct "
            "grains (zone-hour vs. agency-month) with different feature sets "
            "(see realdata/train_real_models.py vs. realdata/"
            "model_ntd_monthly.py). Two models sharing a "
            "feature_schema_version string were trained on the identical "
            "feature list; two models with different strings were not, even "
            "though both perform this task."
        ),
    ),
}


def get_task(task: str) -> TaskDescriptor:
    """Look up a task descriptor, or raise if `task` is not a real task here."""
    try:
        return TASK_REGISTRY[task]
    except KeyError:
        raise UnknownTaskError(
            f"{task!r} is not in the closed task vocabulary: "
            f"{sorted(TASK_REGISTRY)}"
        ) from None
