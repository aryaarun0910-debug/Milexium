"""Time semantics for the canonical contract (v0.1).

Program A requires explicit requested, negotiated, scheduled, predicted, and
actual time fields (blueprint/14-execution-roadmap.md, Program A) plus
bitemporal records where a correction preserves the original decision horizon
rather than overwriting it (blueprint/01-north-star-and-boundaries.md).

Two distinct notions of time are kept separate on purpose:

- **Valid time** (`RequestTimes` below): when things happened or are believed
  to happen in the operational world (the rider asked at 08:03; the pickup
  window was negotiated for 08:15-08:30; ...).
- **Transaction time** (`BitemporalMeta`): when Milexium recorded a version of
  the facts. A correction made today to yesterday's request gets a new
  transaction time but must not change the original decision horizon -- a
  forecast made before the correction was known must still be evaluable
  against what was actually knowable at the time it was made.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from typing import Annotated


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware (UTC)")
    if value.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError(f"timestamps must be UTC, got offset {value.utcoffset()}")
    return value


UtcDateTime = Annotated[datetime, AfterValidator(_require_utc)]


class RequestTimes(BaseModel):
    """The explicit time fields Program A requires for a service request.

    Every field after `requested_at` is optional because, at any point in the
    request's lifecycle, most of them are not yet known -- that is the point
    of keeping them distinct instead of collapsing them into one "when" field.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    requested_at: UtcDateTime = Field(
        description="When the request was made (the fact that starts the aggregate)."
    )
    negotiated_window_start: UtcDateTime | None = Field(
        default=None,
        description="Start of the pickup window agreed with the rider/agency.",
    )
    negotiated_window_end: UtcDateTime | None = Field(
        default=None,
        description="End of the pickup window agreed with the rider/agency.",
    )
    scheduled_pickup_at: UtcDateTime | None = Field(
        default=None,
        description="The pickup time a schedule run actually assigned.",
    )
    predicted_pickup_at: UtcDateTime | None = Field(
        default=None,
        description=(
            "A forecast's predicted pickup time, kept distinct from the "
            "scheduled time so a forecast can be scored against what was "
            "actually scheduled, and both against the actual outcome."
        ),
    )
    actual_pickup_at: UtcDateTime | None = Field(
        default=None, description="The observed, ground-truth pickup time."
    )

    def known_as_of(self, instant: datetime) -> "RequestTimes":
        """Return only the fields that a valid-time reading at `instant` may see.

        Used by replay (Program H/I) to enforce that a replayed decision only
        sees times that had actually occurred by the replay instant, not
        future information leaking backward.
        """
        _require_utc(instant)
        data = self.model_dump()
        for key in (
            "negotiated_window_start",
            "negotiated_window_end",
            "scheduled_pickup_at",
            "predicted_pickup_at",
            "actual_pickup_at",
        ):
            value = data[key]
            if value is not None and value > instant:
                data[key] = None
        return RequestTimes(**data)


class BitemporalMeta(BaseModel):
    """Transaction-time envelope attached to every versioned canonical record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = Field(ge=1, description="Monotonic version number for this aggregate.")
    recorded_at: UtcDateTime = Field(
        description="When Milexium recorded this version (transaction time)."
    )
    corrects_version: int | None = Field(
        default=None,
        description=(
            "The version number this record corrects, if any. None for the "
            "first version. A correction is a new version, never a mutation "
            "of the one it corrects."
        ),
    )

    def is_correction(self) -> bool:
        return self.corrects_version is not None
