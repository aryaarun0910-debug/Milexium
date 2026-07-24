"""Leakage-safe point-in-time feature store (Program D contract, v0.1 slice).

Program D's adaptive memory needs a place to read features "as they were known
at time t" so a forecast is only ever built from information available strictly
before its label time -- the same mechanical point-in-time discipline
`realdata/leakage_audit.py` proves for the training pipelines, here made a
first-class runtime store rather than a per-pipeline convention.

The one invariant that matters:

    get_features(entity_id, as_of=t) returns, per feature, the latest value
    whose knowledge/valid time is STRICTLY < t.

A value stamped exactly at t -- or later -- is never visible. That strict `<`
is the leakage guarantee: a reading at label time t cannot see a fact that only
became known at t or in its future, so a feature built from this store cannot
secretly depend on the future (the corruption test in
`conformance/property-tests/test_feature_store.py` proves it mechanically, the
way `realdata/leakage_audit.py` does for the AAR / NTD panels).

In-memory reference implementation only, matching the pattern
`packages/canonical/events.py`'s `HashChainAppender` and
`packages/core/model_registry.py`'s `ModelRegistry` already established: a
single reference backend plus conformance tests, not a new SQL table. Full
Program D adds tiered memory, feature contracts, and a persistent store; those
stay Specified (`blueprint/05-core-model-runtime-and-forecast.md`).

Privacy: entity ids are opaque strings only -- never a raw name, mirroring
`ServiceRequest.rider_ref`'s tokenization discipline (blueprint 10 data
minimization). The store neither parses nor validates the id's structure; it is
the caller's job to have tokenized it upstream.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from packages.canonical.time import UtcDateTime, _require_utc


class FeatureValue(BaseModel):
    """One (entity, feature) observation stamped with the time it became known.

    `knowledge_time` is a transaction/valid time in the sense of
    `packages/canonical/time.py`: the instant this value first became available
    to be read. An as-of read at label time t admits this value only when
    `knowledge_time < t` (strictly).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: str
    feature_name: str
    value: float
    knowledge_time: UtcDateTime


class FeatureStore:
    """In-memory reference point-in-time feature store.

    Values are appended, never mutated -- a correction is a new `FeatureValue`
    with a later (or equal) `knowledge_time`, never an in-place edit, mirroring
    the append-only discipline of the canonical event log. Reads are resolved
    as-of a label time with the strict past-only rule above.
    """

    def __init__(self) -> None:
        # (entity_id, feature_name) -> observations in append order.
        self._series: dict[tuple[str, str], list[FeatureValue]] = {}

    def write(
        self,
        *,
        entity_id: str,
        feature_name: str,
        value: float,
        knowledge_time: datetime,
    ) -> FeatureValue:
        """Append one observation. `knowledge_time` must be timezone-aware UTC
        (the same rule every canonical timestamp obeys)."""
        _require_utc(knowledge_time)
        observation = FeatureValue(
            entity_id=entity_id,
            feature_name=feature_name,
            value=float(value),
            knowledge_time=knowledge_time,
        )
        self._series.setdefault((entity_id, feature_name), []).append(observation)
        return observation

    def _feature_names(self, entity_id: str) -> tuple[str, ...]:
        return tuple(
            name for (eid, name) in self._series if eid == entity_id
        )

    def get_feature(
        self, entity_id: str, feature_name: str, *, as_of: datetime
    ) -> float | None:
        """The latest value for one feature whose `knowledge_time` is STRICTLY
        earlier than `as_of`, or `None` if no such value exists.

        Ties on `knowledge_time` resolve to the last-written value (a correction
        recorded at the same instant supersedes what it corrects), matching the
        canonical bitemporal "latest recorded version wins" rule.
        """
        _require_utc(as_of)
        series = self._series.get((entity_id, feature_name))
        if not series:
            return None
        latest: FeatureValue | None = None
        for observation in series:  # append order, so ties keep the last write
            if observation.knowledge_time < as_of and (
                latest is None or observation.knowledge_time >= latest.knowledge_time
            ):
                latest = observation
        return latest.value if latest is not None else None

    def get_features(self, entity_id: str, *, as_of: datetime) -> dict[str, float]:
        """Every feature known for `entity_id` as-of `as_of`, each resolved by
        the strict past-only rule of `get_feature`. Features with no value
        strictly before `as_of` are omitted."""
        _require_utc(as_of)
        result: dict[str, float] = {}
        for feature_name in self._feature_names(entity_id):
            value = self.get_feature(entity_id, feature_name, as_of=as_of)
            if value is not None:
                result[feature_name] = value
        return result

    def history(self, entity_id: str, feature_name: str) -> tuple[FeatureValue, ...]:
        """Every recorded observation for one (entity, feature), in append
        order -- the audit view, distinct from the as-of read."""
        return tuple(self._series.get((entity_id, feature_name), ()))

    def entities(self) -> frozenset[str]:
        return frozenset(entity_id for entity_id, _ in self._series)
