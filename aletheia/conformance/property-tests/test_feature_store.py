"""Conformance for the leakage-safe point-in-time feature store
(themis/core/feature_store.py), Program D's adaptive-memory v0.1 slice.

Two things are proven:

1. The as-of read is strictly past-only: get_features(entity, as_of=t) returns,
   per feature, the latest value whose knowledge time is STRICTLY < t -- never a
   value stamped exactly at t or later. That strict `<` is the leakage
   guarantee.
2. A mechanical future-corruption test analogous to data/curated/leakage_audit.py,
   run on a REAL aggregate panel: corrupt every row stamped after a cutoff,
   rebuild the store, and assert every as-of read at a label time <= cutoff is
   bit-identical to the baseline. If a past read changed when only the future
   was corrupted, the store would be leaking; it does not.

The real panel is NYC Access-A-Ride daily scheduled trips
(data/curated/panels/aar_daily.csv) -- REAL public aggregate data, labelled as such
below. The synthetic cases are labelled synthetic. Status: Demonstrated.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from themis.core.feature_store import FeatureStore

# --- REAL aggregate panel (labelled): NYC Access-A-Ride daily scheduled trips.
_AAR_DAILY = Path(__file__).resolve().parents[3] / "data" / "curated" / "panels" / "aar_daily.csv"


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Strict past-only read (SYNTHETIC, fully controlled)
# --------------------------------------------------------------------------- #
def test_asof_read_returns_latest_strictly_past_value() -> None:
    store = FeatureStore()
    store.write(entity_id="z-1", feature_name="lag1", value=10.0, knowledge_time=_utc(2026, 1, 1))
    store.write(entity_id="z-1", feature_name="lag1", value=20.0, knowledge_time=_utc(2026, 1, 2))
    store.write(entity_id="z-1", feature_name="lag1", value=30.0, knowledge_time=_utc(2026, 1, 3))
    # as-of 2026-01-03 sees 01-01 and 01-02 (strictly earlier), latest = 20.0
    assert store.get_feature("z-1", "lag1", as_of=_utc(2026, 1, 3)) == 20.0


def test_asof_read_excludes_a_value_stamped_exactly_at_t() -> None:
    """The failure injection: a read at t must NOT see a value stamped at t."""
    store = FeatureStore()
    store.write(entity_id="z-1", feature_name="f", value=1.0, knowledge_time=_utc(2026, 1, 1))
    store.write(entity_id="z-1", feature_name="f", value=99.0, knowledge_time=_utc(2026, 1, 2))
    # exactly at the second stamp: the 99.0 is invisible, only the 01-01 value shows
    assert store.get_feature("z-1", "f", as_of=_utc(2026, 1, 2)) == 1.0


def test_asof_read_excludes_future_values() -> None:
    store = FeatureStore()
    store.write(entity_id="z-1", feature_name="f", value=5.0, knowledge_time=_utc(2026, 6, 1))
    # a label time before any knowledge time sees nothing
    assert store.get_feature("z-1", "f", as_of=_utc(2026, 1, 1)) is None


def test_get_features_returns_per_feature_latest_strictly_past() -> None:
    store = FeatureStore()
    store.write(entity_id="z-1", feature_name="lag1", value=1.0, knowledge_time=_utc(2026, 1, 1))
    store.write(entity_id="z-1", feature_name="lag1", value=2.0, knowledge_time=_utc(2026, 1, 5))
    store.write(entity_id="z-1", feature_name="roll7", value=3.0, knowledge_time=_utc(2026, 1, 2))
    store.write(entity_id="z-1", feature_name="roll7", value=4.0, knowledge_time=_utc(2026, 1, 9))
    got = store.get_features("z-1", as_of=_utc(2026, 1, 6))
    # lag1: 01-05 (<06) latest -> 2.0 ; roll7: 01-02 (<06) latest, 01-09 in the future -> 3.0
    assert got == {"lag1": 2.0, "roll7": 3.0}


def test_features_absent_before_their_first_knowledge_time_are_omitted() -> None:
    store = FeatureStore()
    store.write(entity_id="z-1", feature_name="early", value=1.0, knowledge_time=_utc(2026, 1, 1))
    store.write(entity_id="z-1", feature_name="late", value=2.0, knowledge_time=_utc(2026, 6, 1))
    got = store.get_features("z-1", as_of=_utc(2026, 2, 1))
    assert got == {"early": 1.0}  # 'late' has no strictly-past value yet


def test_same_knowledge_time_last_write_wins() -> None:
    """A correction recorded at the same instant supersedes what it corrects
    (canonical 'latest recorded version wins')."""
    store = FeatureStore()
    store.write(entity_id="z-1", feature_name="f", value=1.0, knowledge_time=_utc(2026, 1, 1))
    store.write(entity_id="z-1", feature_name="f", value=1.5, knowledge_time=_utc(2026, 1, 1))  # correction
    assert store.get_feature("z-1", "f", as_of=_utc(2026, 1, 2)) == 1.5


def test_entities_are_isolated() -> None:
    store = FeatureStore()
    store.write(entity_id="z-1", feature_name="f", value=1.0, knowledge_time=_utc(2026, 1, 1))
    store.write(entity_id="z-2", feature_name="f", value=2.0, knowledge_time=_utc(2026, 1, 1))
    assert store.get_feature("z-1", "f", as_of=_utc(2026, 1, 2)) == 1.0
    assert store.get_feature("z-2", "f", as_of=_utc(2026, 1, 2)) == 2.0
    assert store.get_feature("z-3", "f", as_of=_utc(2026, 1, 2)) is None


def test_asof_must_be_timezone_aware_utc() -> None:
    store = FeatureStore()
    store.write(entity_id="z-1", feature_name="f", value=1.0, knowledge_time=_utc(2026, 1, 1))
    with pytest.raises(ValueError):
        store.get_feature("z-1", "f", as_of=datetime(2026, 1, 2))  # naive -> rejected


def test_write_rejects_naive_knowledge_time() -> None:
    store = FeatureStore()
    with pytest.raises(ValueError):
        store.write(entity_id="z-1", feature_name="f", value=1.0, knowledge_time=datetime(2026, 1, 1))


def test_history_is_append_only_audit_view() -> None:
    store = FeatureStore()
    store.write(entity_id="z-1", feature_name="f", value=1.0, knowledge_time=_utc(2026, 1, 1))
    store.write(entity_id="z-1", feature_name="f", value=2.0, knowledge_time=_utc(2026, 1, 2))
    history = store.history("z-1", "f")
    assert [v.value for v in history] == [1.0, 2.0]  # both retained, in append order


# --------------------------------------------------------------------------- #
# Mechanical future-corruption leakage test on the REAL AAR daily panel
# (analogous to data/curated/leakage_audit.py)
# --------------------------------------------------------------------------- #
_ENTITY = "aar_nyc_scheduled_trips"  # opaque id, no PII
_FEATURE = "scheduled_trips"


def _load_aar_daily() -> list[tuple[datetime, float]]:
    import pandas as pd

    df = pd.read_csv(_AAR_DAILY, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    return [
        (ts.to_pydatetime().replace(tzinfo=timezone.utc), float(v))
        for ts, v in zip(df["date"], df["scheduled_trips"])
    ]


def _build_store(rows: list[tuple[datetime, float]]) -> FeatureStore:
    store = FeatureStore()
    for knowledge_time, value in rows:
        store.write(
            entity_id=_ENTITY, feature_name=_FEATURE, value=value, knowledge_time=knowledge_time
        )
    return store


@pytest.mark.skipif(not _AAR_DAILY.exists(), reason="real AAR daily panel absent")
def test_real_panel_asof_read_is_strictly_past() -> None:
    """REAL DATA: an as-of read at day d returns the count known the previous
    observed day, never day d's own (same-stamp) value."""
    rows = _load_aar_daily()
    store = _build_store(rows)
    # read at the third observed day's stamp -> must equal the SECOND day's value
    third_day = rows[2][0]
    assert store.get_feature(_ENTITY, _FEATURE, as_of=third_day) == rows[1][1]


@pytest.mark.skipif(not _AAR_DAILY.exists(), reason="real AAR daily panel absent")
def test_real_panel_future_corruption_leaves_past_bit_identical() -> None:
    """REAL DATA, the mechanical leakage guarantee (mirrors
    data/curated/leakage_audit.py): corrupt every row stamped after a cutoff,
    rebuild, and assert every as-of read at a label time <= cutoff is
    bit-identical. Run at several cutoffs across the timeline."""
    rows = _load_aar_daily()
    baseline = _build_store(rows)
    dates = [d for d, _ in rows]
    rng = np.random.default_rng(0)

    for cutoff in (dates[len(dates) // 4], dates[len(dates) // 2], dates[3 * len(dates) // 4]):
        # corrupt every value whose knowledge time is strictly after the cutoff
        corrupted_rows = [
            (d, (float(rng.integers(10_000_000, 100_000_000)) if d > cutoff else v))
            for d, v in rows
        ]
        rebuilt = _build_store(corrupted_rows)

        # every as-of read at a label time at/<= cutoff must be untouched
        checked = 0
        for label_time in dates:
            if label_time > cutoff:
                continue
            before = baseline.get_feature(_ENTITY, _FEATURE, as_of=label_time)
            after = rebuilt.get_feature(_ENTITY, _FEATURE, as_of=label_time)
            assert before == after, f"leak at as_of={label_time} cutoff={cutoff}: {before} != {after}"
            checked += 1
        assert checked > 0  # the cutoff actually exercised some past reads


@pytest.mark.skipif(not _AAR_DAILY.exists(), reason="real AAR daily panel absent")
def test_real_panel_corruption_would_change_a_future_read() -> None:
    """REAL DATA control: the corruption is real -- a read whose label time is
    AFTER the cutoff (thus allowed to see corrupted rows) DOES change. This
    proves the bit-identical result above is the strict-past rule at work, not
    an inert no-op corruption."""
    rows = _load_aar_daily()
    baseline = _build_store(rows)
    dates = [d for d, _ in rows]
    cutoff = dates[len(dates) // 2]
    rng = np.random.default_rng(1)
    corrupted_rows = [
        (d, (float(rng.integers(10_000_000, 100_000_000)) if d > cutoff else v)) for d, v in rows
    ]
    rebuilt = _build_store(corrupted_rows)
    # a label time well after the cutoff sees the corrupted future -> differs
    late = dates[-1]
    assert baseline.get_feature(_ENTITY, _FEATURE, as_of=late) != rebuilt.get_feature(
        _ENTITY, _FEATURE, as_of=late
    )
