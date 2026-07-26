"""Capture an ADR-0039 deadhead teardown into pack-carriable evidence.

This is the ONLY module in `app/evidence` that imports `app.replay`,
and it is deliberately on the *generator* side of the line: it converts a
`DeadheadTeardown` plus the `VehicleSegment`s it ran on into the plain models of
`app/evidence/teardown_evidence.py`. The verification path -- the pack
model, `verify_evidence_pack`, and `rederive_teardown` -- never imports the
generator at all, so a re-derivation cannot be satisfied by the generator
agreeing with itself.

Two refusals live here, both at build time, because a pack that is wrong is
worse than no pack:

- **Data binding.** The segments handed in are fingerprinted with the
  verification module's own independent implementation and compared to the
  manifest's `segment_sha256`. A teardown and a segment set that do not belong
  together cannot be packed.
- **Self-check.** The finished evidence is put through the same
  `rederive_teardown` a third party will run. If the figures do not re-derive,
  capture raises instead of shipping a bundle that fails on the recipient's
  desk.

Framing is **carried, not restated**: `FIXED_COST_HEDGE`, `DEADHEAD_TEARDOWN_NOTE`
and `MODELLED_COMPARISON_NOTE` are imported from their single source and asserted
verbatim on the way in, so the pack cannot drift into softer wording than the
analysis it carries.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.evidence.teardown_evidence import (
    TeardownBucketRow,
    TeardownEvidence,
    TeardownFigures,
    TeardownRunRow,
    TeardownSegmentRow,
    rederive_segment_fingerprint,
    rederive_teardown,
)
from app.replay.comparison import MODELLED_COMPARISON_NOTE
from app.replay.teardown import (
    DEADHEAD_TEARDOWN_NOTE,
    FIXED_COST_HEDGE,
    DeadheadTeardown,
    RunContribution,
    TimeBucket,
    VehicleSegment,
)


class TeardownCaptureError(ValueError):
    """Raised when a teardown cannot be packed honestly -- segments that are not
    the ones it was computed from, or framing that no longer matches its
    single source."""


def _segment_rows(segments: Iterable[VehicleSegment]) -> tuple[TeardownSegmentRow, ...]:
    """Exactly the four structural fields, named one by one. Nothing else on a
    segment can be carried into a pack even if a future field appeared on
    `VehicleSegment`, which is the same reason `VehicleSegment.from_row` reads
    only the columns it is pointed at."""
    return tuple(
        TeardownSegmentRow(
            started_at=segment.started_at.isoformat(),
            ended_at=segment.ended_at.isoformat(),
            kind=segment.kind,
            run_ref=segment.run_ref,
        )
        for segment in segments
    )


def _bucket_row(bucket: TimeBucket) -> TeardownBucketRow:
    return TeardownBucketRow(
        day_of_week=bucket.day_of_week,
        hour_of_day=bucket.hour_of_day,
        deadhead_minutes=bucket.deadhead_minutes,
        revenue_minutes=bucket.revenue_minutes,
        deadhead_share_of_bucket=bucket.deadhead_share_of_bucket,
        share_of_total_deadhead=bucket.share_of_total_deadhead,
    )


def _run_row(run: RunContribution) -> TeardownRunRow:
    return TeardownRunRow(
        run_ref=run.run_ref,
        attributable=run.attributable,
        deadhead_minutes=run.deadhead_minutes,
        revenue_minutes=run.revenue_minutes,
        segment_count=run.segment_count,
        share_of_total_deadhead=run.share_of_total_deadhead,
    )


def _assert_framing_survives(teardown: DeadheadTeardown) -> None:
    """The hedges must reach the pack verbatim. A pack that softened them would
    be the exact failure mode ADR-0019 exists to prevent, and it would be
    invisible -- the numbers would still be right."""
    manifest = teardown.manifest
    if teardown.interpretation != DEADHEAD_TEARDOWN_NOTE or manifest.note != DEADHEAD_TEARDOWN_NOTE:
        raise TeardownCaptureError(
            "refusing to pack a teardown whose modelled-not-causal note is not "
            "DEADHEAD_TEARDOWN_NOTE verbatim: the framing is carried, never restated"
        )
    if manifest.replay_discipline_note != MODELLED_COMPARISON_NOTE:
        raise TeardownCaptureError(
            "refusing to pack a teardown whose replay_discipline_note is not "
            "MODELLED_COMPARISON_NOTE verbatim (ADR-0019)"
        )
    if teardown.causal_proof:
        raise TeardownCaptureError("refusing to pack a teardown claiming causal proof")
    if teardown.cost is not None:
        if teardown.cost.is_guaranteed_saving:
            raise TeardownCaptureError(
                "refusing to pack a cost envelope presented as a guaranteed saving"
            )
        if teardown.cost.hedge != FIXED_COST_HEDGE:
            raise TeardownCaptureError(
                "refusing to pack a cost envelope whose hedge is not FIXED_COST_HEDGE "
                "verbatim: the envelope and its hedge travel together or not at all"
            )


def capture_teardown(
    teardown: DeadheadTeardown, segments: Iterable[VehicleSegment]
) -> TeardownEvidence:
    """Turn a `DeadheadTeardown` and the segments it ran on into evidence a pack
    can carry and a third party can recompute.

    `segments` is required, not optional: a teardown whose inputs were not
    embedded is a number to be taken on trust, and a number taken on trust is
    not evidence. The figures are re-derived here before the evidence is
    returned, so an unverifiable pack cannot be produced by accident.
    """
    _assert_framing_survives(teardown)

    manifest = teardown.manifest
    rows = _segment_rows(segments)

    if len(rows) != manifest.segment_count:
        raise TeardownCaptureError(
            f"refusing to pack {len(rows)} segments against a manifest recording "
            f"{manifest.segment_count}: these are not the segments this teardown was "
            "computed from"
        )
    recomputed = rederive_segment_fingerprint(rows)
    if recomputed != manifest.segment_sha256:
        raise TeardownCaptureError(
            f"segment fingerprint mismatch: manifest says {manifest.segment_sha256}, "
            f"the supplied segments fingerprint to {recomputed}. A pack must embed "
            "the exact segment set its figures were derived from."
        )

    cost = teardown.cost
    figures = TeardownFigures(
        total_deadhead_minutes=teardown.total_deadhead_minutes,
        total_revenue_minutes=teardown.total_revenue_minutes,
        deadhead_share_of_vehicle_time=teardown.deadhead_share_of_vehicle_time,
        deadhead_hours=None if cost is None else cost.deadhead_hours,
        value_at_full_cost=None if cost is None else cost.value_at_full_cost,
        modelled_envelope_low=None if cost is None else cost.modelled_envelope_low,
        modelled_envelope_high=None if cost is None else cost.modelled_envelope_high,
        currency=None if cost is None else cost.currency,
        envelope_basis=None if cost is None else cost.envelope_basis,
        hedge=None if cost is None else cost.hedge,
    )

    evidence = TeardownEvidence(
        manifest=manifest.model_dump(mode="json"),
        teardown_id=manifest.teardown_id,
        data_provenance=manifest.data_provenance,
        figures=figures,
        by_hour_of_day=tuple(_bucket_row(b) for b in teardown.by_hour_of_day),
        by_day_of_week=tuple(_bucket_row(b) for b in teardown.by_day_of_week),
        top_runs=tuple(_run_row(r) for r in teardown.top_runs),
        unattributable=None if teardown.unattributable is None else _run_row(teardown.unattributable),
        attributed_run_count=teardown.attributed_run_count,
        segments=rows,
        interpretation=teardown.interpretation,
    )

    check = rederive_teardown(evidence)
    if not check.figures_rederived or check.fingerprint_rederived is False:
        raise TeardownCaptureError(
            "refusing to emit a teardown pack whose own figures do not re-derive "
            f"from the segments it embeds: {'; '.join(check.mismatches)}"
        )
    return evidence
