"""Conformance for the champion/challenger/canary promotion controller
(themis/core/promotion.py), Program D's adaptive-memory v0.1 slice.

Proves the lifecycle beyond ADR-0010's single champion pointer:

- A challenger becomes champion ONLY through the evaluated gate, which records a
  PromotionDecision (the metric comparison + verdict). No incumbent -> installed
  as first champion; an incumbent -> promoted only on a real improvement, in the
  stated direction, clearing min_improvement.
- A canary carries a traffic fraction in [0, 1) and routing honours it.
- Rollback demotes to the previous champion and is recorded.
- The controller COMPOSES ModelRegistry and never mutates it (the registry's own
  champion pointer stays untouched).

All model versions here are SYNTHETIC fixtures; the controller logic is what is
under test. Status: Demonstrated.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from themis.canonical import ModelVersion, ModelVersionId, TenantId, new_id
from themis.core.model_registry import ModelRegistry, UnknownModelVersionError
from themis.core.promotion import (
    NoRollbackTargetError,
    PromotionController,
    PromotionError,
    RoleAssignmentError,
    TrafficFractionError,
)

TASK = "forecast.demand"


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _model_version(**overrides) -> ModelVersion:
    fields = dict(
        model_version_id=new_id(ModelVersionId),
        tenant_id=new_id(TenantId),
        task=TASK,
        training_data_manifest_hash="deadbeef" * 8,
        feature_schema_version="zone_hour_demand_v1",
        evaluation_window_start=_utc(2026, 3, 2),
        evaluation_window_end=_utc(2026, 5, 31),
        artifact_hash="cafebabe" * 8,
    )
    fields.update(overrides)
    return ModelVersion(**fields)


def _registry_with(*versions: ModelVersion) -> ModelRegistry:
    registry = ModelRegistry()
    for v in versions:
        registry.register(v)
    return registry


# --------------------------------------------------------------------------- #
# The evaluated gate
# --------------------------------------------------------------------------- #
def test_first_challenger_is_installed_as_champion_through_the_gate() -> None:
    a = _model_version()
    controller = PromotionController(_registry_with(a))
    controller.register_challenger(TASK, a.model_version_id)
    decision = controller.evaluate_and_maybe_promote(
        TASK, a.model_version_id, metric_name="wape", challenger_metric=0.2,
        higher_is_better=False, decided_at=_utc(2026, 6, 1),
    )
    assert decision.promoted is True
    assert decision.incumbent_id is None
    assert controller.champion(TASK) == a.model_version_id
    assert a.model_version_id not in controller.challengers(TASK)


def test_challenger_that_beats_champion_is_promoted() -> None:
    champ, chal = _model_version(), _model_version()
    controller = PromotionController(_registry_with(champ, chal))
    controller.register_challenger(TASK, champ.model_version_id)
    controller.evaluate_and_maybe_promote(
        TASK, champ.model_version_id, metric_name="r2", challenger_metric=0.5,
        decided_at=_utc(2026, 6, 1),
    )
    controller.register_challenger(TASK, chal.model_version_id)
    decision = controller.evaluate_and_maybe_promote(
        TASK, chal.model_version_id, metric_name="r2", challenger_metric=0.7,
        incumbent_metric=0.5, higher_is_better=True, decided_at=_utc(2026, 6, 2),
    )
    assert decision.promoted is True
    assert decision.margin == pytest.approx(0.2)
    assert controller.champion(TASK) == chal.model_version_id


def test_challenger_no_better_than_champion_is_not_promoted() -> None:
    champ, chal = _model_version(), _model_version()
    controller = PromotionController(_registry_with(champ, chal))
    controller.register_challenger(TASK, champ.model_version_id)
    controller.evaluate_and_maybe_promote(
        TASK, champ.model_version_id, metric_name="r2", challenger_metric=0.6,
        decided_at=_utc(2026, 6, 1),
    )
    controller.register_challenger(TASK, chal.model_version_id)
    decision = controller.evaluate_and_maybe_promote(  # equal metric -> no gain
        TASK, chal.model_version_id, metric_name="r2", challenger_metric=0.6,
        incumbent_metric=0.6, higher_is_better=True, decided_at=_utc(2026, 6, 2),
    )
    assert decision.promoted is False
    assert controller.champion(TASK) == champ.model_version_id
    assert chal.model_version_id in controller.challengers(TASK)  # stays a challenger


def test_min_improvement_gate_blocks_a_marginal_gain() -> None:
    champ, chal = _model_version(), _model_version()
    controller = PromotionController(_registry_with(champ, chal))
    controller.register_challenger(TASK, champ.model_version_id)
    controller.evaluate_and_maybe_promote(
        TASK, champ.model_version_id, metric_name="r2", challenger_metric=0.60,
        decided_at=_utc(2026, 6, 1),
    )
    controller.register_challenger(TASK, chal.model_version_id)
    decision = controller.evaluate_and_maybe_promote(
        TASK, chal.model_version_id, metric_name="r2", challenger_metric=0.605,
        incumbent_metric=0.60, higher_is_better=True, min_improvement=0.02,
        decided_at=_utc(2026, 6, 2),
    )
    assert decision.promoted is False  # +0.005 < required 0.02
    assert controller.champion(TASK) == champ.model_version_id


def test_lower_is_better_direction_is_respected() -> None:
    champ, chal = _model_version(), _model_version()
    controller = PromotionController(_registry_with(champ, chal))
    controller.register_challenger(TASK, champ.model_version_id)
    controller.evaluate_and_maybe_promote(
        TASK, champ.model_version_id, metric_name="wape", challenger_metric=0.15,
        higher_is_better=False, decided_at=_utc(2026, 6, 1),
    )
    controller.register_challenger(TASK, chal.model_version_id)
    decision = controller.evaluate_and_maybe_promote(
        TASK, chal.model_version_id, metric_name="wape", challenger_metric=0.10,
        incumbent_metric=0.15, higher_is_better=False, decided_at=_utc(2026, 6, 2),
    )
    assert decision.promoted is True  # lower WAPE is better
    assert decision.margin == pytest.approx(0.05)


def test_gate_requires_a_registered_challenger() -> None:
    a = _model_version()
    controller = PromotionController(_registry_with(a))
    with pytest.raises(RoleAssignmentError):  # never registered as a challenger
        controller.evaluate_and_maybe_promote(
            TASK, a.model_version_id, metric_name="r2", challenger_metric=0.5,
            decided_at=_utc(2026, 6, 1),
        )


def test_gate_against_incumbent_requires_incumbent_metric() -> None:
    champ, chal = _model_version(), _model_version()
    controller = PromotionController(_registry_with(champ, chal))
    controller.register_challenger(TASK, champ.model_version_id)
    controller.evaluate_and_maybe_promote(
        TASK, champ.model_version_id, metric_name="r2", challenger_metric=0.5,
        decided_at=_utc(2026, 6, 1),
    )
    controller.register_challenger(TASK, chal.model_version_id)
    with pytest.raises(PromotionError):  # no incumbent_metric to compare against
        controller.evaluate_and_maybe_promote(
            TASK, chal.model_version_id, metric_name="r2", challenger_metric=0.9,
            decided_at=_utc(2026, 6, 2),
        )


def test_register_challenger_requires_a_registered_version() -> None:
    controller = PromotionController(ModelRegistry())
    with pytest.raises(UnknownModelVersionError):
        controller.register_challenger(TASK, new_id(ModelVersionId))


# --------------------------------------------------------------------------- #
# Canary + routing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", [1.0, 1.5, -0.1])
def test_canary_fraction_out_of_range_is_rejected(bad: float) -> None:
    champ, chal = _model_version(), _model_version()
    controller = PromotionController(_registry_with(champ, chal))
    controller.register_challenger(TASK, chal.model_version_id)
    with pytest.raises(TrafficFractionError):
        controller.set_canary(TASK, chal.model_version_id, bad)


def test_canary_fraction_zero_is_allowed_and_takes_no_traffic() -> None:
    chal = _model_version()
    controller = PromotionController(_registry_with(chal))
    controller.register_challenger(TASK, chal.model_version_id)
    controller.set_canary(TASK, chal.model_version_id, 0.0)  # staged, no live traffic
    assert controller.canary(TASK) == (chal.model_version_id, 0.0)
    assert controller.route(TASK, 0.0) is None  # no champion yet, canary at 0 -> nothing


def test_canary_must_be_a_challenger_first() -> None:
    chal = _model_version()
    controller = PromotionController(_registry_with(chal))
    with pytest.raises(RoleAssignmentError):
        controller.set_canary(TASK, chal.model_version_id, 0.2)


def test_routing_honours_the_canary_fraction() -> None:
    champ, chal = _model_version(), _model_version()
    controller = PromotionController(_registry_with(champ, chal))
    controller.register_challenger(TASK, champ.model_version_id)
    controller.evaluate_and_maybe_promote(
        TASK, champ.model_version_id, metric_name="r2", challenger_metric=0.5,
        decided_at=_utc(2026, 6, 1),
    )
    controller.register_challenger(TASK, chal.model_version_id)
    controller.set_canary(TASK, chal.model_version_id, 0.3)
    assert controller.route(TASK, 0.0) == chal.model_version_id    # roll < 0.3 -> canary
    assert controller.route(TASK, 0.29) == chal.model_version_id
    assert controller.route(TASK, 0.3) == champ.model_version_id   # roll >= 0.3 -> champion
    assert controller.route(TASK, 0.99) == champ.model_version_id


def test_route_rejects_a_roll_out_of_range() -> None:
    controller = PromotionController(ModelRegistry())
    with pytest.raises(TrafficFractionError):
        controller.route(TASK, 1.0)


def test_promoting_the_canary_clears_it() -> None:
    champ, chal = _model_version(), _model_version()
    controller = PromotionController(_registry_with(champ, chal))
    controller.register_challenger(TASK, champ.model_version_id)
    controller.evaluate_and_maybe_promote(
        TASK, champ.model_version_id, metric_name="r2", challenger_metric=0.5,
        decided_at=_utc(2026, 6, 1),
    )
    controller.register_challenger(TASK, chal.model_version_id)
    controller.set_canary(TASK, chal.model_version_id, 0.5)
    controller.evaluate_and_maybe_promote(
        TASK, chal.model_version_id, metric_name="r2", challenger_metric=0.9,
        incumbent_metric=0.5, decided_at=_utc(2026, 6, 2),
    )
    assert controller.champion(TASK) == chal.model_version_id
    assert controller.canary(TASK) is None


def test_demote_challenger_removes_it_and_clears_its_canary() -> None:
    chal = _model_version()
    controller = PromotionController(_registry_with(chal))
    controller.register_challenger(TASK, chal.model_version_id)
    controller.set_canary(TASK, chal.model_version_id, 0.2)
    controller.demote_challenger(TASK, chal.model_version_id)
    assert chal.model_version_id not in controller.challengers(TASK)
    assert controller.canary(TASK) is None
    with pytest.raises(RoleAssignmentError):
        controller.demote_challenger(TASK, chal.model_version_id)  # already gone


# --------------------------------------------------------------------------- #
# Rollback + recording
# --------------------------------------------------------------------------- #
def _promote_two_champions() -> tuple[PromotionController, ModelVersion, ModelVersion]:
    first, second = _model_version(), _model_version()
    controller = PromotionController(_registry_with(first, second))
    controller.register_challenger(TASK, first.model_version_id)
    controller.evaluate_and_maybe_promote(
        TASK, first.model_version_id, metric_name="r2", challenger_metric=0.5,
        decided_at=_utc(2026, 6, 1),
    )
    controller.register_challenger(TASK, second.model_version_id)
    controller.evaluate_and_maybe_promote(
        TASK, second.model_version_id, metric_name="r2", challenger_metric=0.7,
        incumbent_metric=0.5, decided_at=_utc(2026, 6, 2),
    )
    return controller, first, second


def test_rollback_restores_the_previous_champion_and_is_recorded() -> None:
    controller, first, second = _promote_two_champions()
    assert controller.champion(TASK) == second.model_version_id
    record = controller.rollback(TASK, decided_at=_utc(2026, 6, 3), reason="canary regressed p95 latency")
    assert controller.champion(TASK) == first.model_version_id
    assert record.from_champion_id == second.model_version_id
    assert record.to_champion_id == first.model_version_id
    assert second.model_version_id in controller.challengers(TASK)  # demoted, re-evaluable
    assert controller.rollbacks() == (record,)


def test_rollback_without_a_prior_champion_raises() -> None:
    a = _model_version()
    controller = PromotionController(_registry_with(a))
    controller.register_challenger(TASK, a.model_version_id)
    controller.evaluate_and_maybe_promote(
        TASK, a.model_version_id, metric_name="r2", challenger_metric=0.5,
        decided_at=_utc(2026, 6, 1),
    )
    with pytest.raises(NoRollbackTargetError):  # only ever one champion
        controller.rollback(TASK, decided_at=_utc(2026, 6, 2), reason="nothing to fall back to")


def test_every_gate_verdict_is_recorded() -> None:
    controller, _first, _second = _promote_two_champions()
    decisions = controller.decisions()
    assert len(decisions) == 2
    assert [d.promoted for d in decisions] == [True, True]
    assert decisions[0].incumbent_id is None
    assert decisions[1].incumbent_id is not None
    assert decisions[1].margin == pytest.approx(0.2)


def test_rollout_snapshot_reports_all_roles() -> None:
    champ, chal = _model_version(), _model_version()
    controller = PromotionController(_registry_with(champ, chal))
    controller.register_challenger(TASK, champ.model_version_id)
    controller.evaluate_and_maybe_promote(
        TASK, champ.model_version_id, metric_name="r2", challenger_metric=0.5,
        decided_at=_utc(2026, 6, 1),
    )
    controller.register_challenger(TASK, chal.model_version_id)
    controller.set_canary(TASK, chal.model_version_id, 0.25)
    snap = controller.rollout(TASK)
    assert snap.champion_id == champ.model_version_id
    assert snap.challenger_ids == (chal.model_version_id,)
    assert snap.canary_id == chal.model_version_id
    assert snap.canary_fraction == pytest.approx(0.25)


# --------------------------------------------------------------------------- #
# Composition, not mutation
# --------------------------------------------------------------------------- #
def test_controller_never_mutates_the_composed_registry() -> None:
    """The controller drives promotions and rollbacks; the registry's OWN
    single-champion pointer (ADR-0010) is never touched by it."""
    registry = ModelRegistry()
    first, second = _model_version(), _model_version()
    registry.register(first)
    registry.register(second)
    controller = PromotionController(registry)
    controller.register_challenger(TASK, first.model_version_id)
    controller.evaluate_and_maybe_promote(
        TASK, first.model_version_id, metric_name="r2", challenger_metric=0.5,
        decided_at=_utc(2026, 6, 1),
    )
    controller.register_challenger(TASK, second.model_version_id)
    controller.evaluate_and_maybe_promote(
        TASK, second.model_version_id, metric_name="r2", challenger_metric=0.7,
        incumbent_metric=0.5, decided_at=_utc(2026, 6, 2),
    )
    controller.rollback(TASK, decided_at=_utc(2026, 6, 3), reason="regression")
    # registry pointer was never set by the controller
    assert registry.champion(TASK) is None
    # and both versions are still exactly as registered
    assert registry.get(first.model_version_id) == first
    assert registry.get(second.model_version_id) == second
