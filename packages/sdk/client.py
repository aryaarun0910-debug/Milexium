"""MilexiumClient: the v0.1 facade over the canonical loop.

This module composes packages already in the repository -- it adds ergonomics
and one stable public surface, not new domain logic. Every method delegates:

- `in_memory` / tenant setup    -> packages.canonical.SqliteCanonicalStore
- `ingest`                      -> packages.connect.adapter.parse_batch
- `record_decision`/`_override` -> SqliteCanonicalStore.append_event
- `evidence_for`                -> packages.evidence.build_evidence_packet
- `export_pack`                 -> packages.evidence.build_evidence_pack
- `forecast`                    -> packages.forecast.ForecastRuntime
- `teardown_deadhead`           -> packages.replay.teardown.teardown_deadhead
- `verify`                      -> packages.verify.verify_chain

The SDK core never imports a *concrete* adapter (ReferenceAgencyTripsAdapter,
TlcTripsAdapter, or the ones other packets are adding). `ingest` takes any
object satisfying the structural `SourceAdapter` protocol -- anything with a
`.parse(raw_row) -> AdapterResult` method -- and runs it through the generic
`parse_batch` runner. That keeps the SDK decoupled from which adapter a caller
uses: a new adapter needs no SDK change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from packages.canonical import (
    DecisionEventType,
    SqliteCanonicalStore,
    Tenant,
    TenantId,
    new_id,
)
from packages.connect.adapter import parse_batch
from packages.evidence import build_evidence_pack, build_evidence_packet
from packages.replay.teardown import DEFAULT_REDUCTION_FRACTION, teardown_deadhead
from packages.verify import verify_chain

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path

    from pydantic import BaseModel

    from packages.canonical import DecisionEvent, ForecastVintage, ModelVersion, Outcome, ReasonCode
    from packages.connect.adapter import (
        QuarantinedRow,
        SemanticLossRecord,
        SourceAdapter,
    )
    from packages.core import ModelRegistry
    from packages.evidence import EvidencePack, EvidencePacket
    from packages.replay.teardown import (
        CostBasis,
        DataProvenance,
        DeadheadTeardown,
        VehicleSegment,
    )
    from packages.verify import ChainViolation


@dataclass(frozen=True)
class IngestSummary:
    """The structured result of one `ingest` call.

    A plain frozen dataclass, not a Pydantic model: it aggregates objects that
    are *already* validated (canonical records straight out of an adapter,
    plus that adapter's own quarantine/semantic-loss records). It performs no
    validation of its own, and `records` is deliberately heterogeneous -- an
    adapter is generic over its canonical output type -- so re-wrapping it in a
    Pydantic model would add re-coercion risk without modeling any new data.
    """

    records: tuple["BaseModel", ...]
    quarantined_rows: tuple["QuarantinedRow", ...]
    semantic_loss: tuple["SemanticLossRecord", ...]

    @property
    def accepted(self) -> int:
        return len(self.records)

    @property
    def quarantined(self) -> int:
        return len(self.quarantined_rows)


class MilexiumClient:
    """One import, one client, the whole v0.1 loop reachable ergonomically.

    Wraps a `SqliteCanonicalStore` bound to a single tenant. The store is
    reachable via `.store` as a deliberate escape hatch for power users and
    adversarial tests; the facade methods are the supported surface.
    """

    def __init__(self, store: SqliteCanonicalStore, tenant_id: TenantId) -> None:
        self._store = store
        self._tenant_id = tenant_id

    @classmethod
    def in_memory(cls, tenant_name: str) -> "MilexiumClient":
        """The ten-minute adoption path: an in-memory SQLite store plus one
        freshly created tenant, zero external infrastructure."""
        store = SqliteCanonicalStore()
        tenant = Tenant(
            tenant_id=new_id(TenantId),
            name=tenant_name,
            created_at=datetime.now(timezone.utc),
        )
        store.create_tenant(tenant)
        return cls(store, tenant.tenant_id)

    @property
    def tenant_id(self) -> TenantId:
        return self._tenant_id

    @property
    def store(self) -> SqliteCanonicalStore:
        """Lower-level canonical store this client wraps -- escape hatch for
        power users and tests, not the primary surface."""
        return self._store

    def ingest(self, adapter: "SourceAdapter", rows: list[dict]) -> IngestSummary:
        """Run any `SourceAdapter` over raw rows and summarize the result.

        Never silently drops a row: every input becomes either a mapped record
        or a quarantine, and every semantic-loss note the adapter emitted is
        surfaced -- honoring the Connect contract rather than reimplementing
        it (the batch runner is `packages.connect.adapter.parse_batch`).
        """
        results = parse_batch(adapter, rows)
        records = tuple(r.record for r in results if r.record is not None)
        quarantined_rows = tuple(r.quarantine for r in results if r.quarantine is not None)
        semantic_loss = tuple(note for r in results for note in r.semantic_loss)
        return IngestSummary(
            records=records,
            quarantined_rows=quarantined_rows,
            semantic_loss=semantic_loss,
        )

    def record_decision(
        self,
        *,
        aggregate_id: str,
        payload: dict,
        actor_id: str = "system",
        aggregate_type: str = "ServiceRequest",
        occurred_at: datetime | None = None,
        reason_codes: "tuple[ReasonCode, ...]" = (),
        idempotency_key: str | None = None,
    ) -> "DecisionEvent":
        """Append a RECOMMENDATION event -- a system act, so `actor_type` is
        fixed to "system" and the caller never hand-builds the event dict."""
        return self._store.append_event(
            tenant_id=self._tenant_id,
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            occurred_at=occurred_at or datetime.now(timezone.utc),
            actor_type="system",
            actor_id=actor_id,
            event_type=DecisionEventType.RECOMMENDATION,
            payload=payload,
            reason_codes=reason_codes,
            idempotency_key=idempotency_key,
        )

    def record_override(
        self,
        *,
        aggregate_id: str,
        payload: dict,
        actor_id: str,
        aggregate_type: str = "ServiceRequest",
        occurred_at: datetime | None = None,
        reason_codes: "tuple[ReasonCode, ...]" = (),
        idempotency_key: str | None = None,
    ) -> "DecisionEvent":
        """Append an OVERRIDE event -- a human act superseding a prior
        recommendation, so `actor_type` is fixed to "human" and `actor_id`
        (the human) is required rather than defaulted."""
        return self._store.append_event(
            tenant_id=self._tenant_id,
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            occurred_at=occurred_at or datetime.now(timezone.utc),
            actor_type="human",
            actor_id=actor_id,
            event_type=DecisionEventType.OVERRIDE,
            payload=payload,
            reason_codes=reason_codes,
            idempotency_key=idempotency_key,
        )

    def evidence_for(
        self, aggregate_id: str, outcome: "Outcome | None" = None
    ) -> "EvidencePacket":
        """Pull an aggregate's history plus this tenant's raw rows and build a
        verified EvidencePacket in one call. `packet.integrity_verified` is the
        real aggregated check result (hash chain + schema), not a claim.

        Raises ValueError (from the builder) if the aggregate has no history."""
        events = self._store.history(self._tenant_id, aggregate_id)
        raw_rows = self._store.raw_rows_for_tenant(self._tenant_id)
        return build_evidence_packet(events, raw_rows, outcome=outcome)

    def export_pack(
        self, aggregate_id: str, outcome: "Outcome | None" = None
    ) -> "EvidencePack":
        """Build a portable, independently-verifiable EvidencePack for one
        aggregate -- the shareable sibling of `evidence_for`.

        Pulls the same history + raw rows as `evidence_for`, but wraps the
        packet with its own raw event bytes and a bundle checksum so a third
        party can re-verify the hash chain WITHOUT Milexium and without a live
        store (packages.evidence.build_evidence_pack). Use `evidence_for` for an
        in-process packet, `export_pack` to hand a partner a self-contained file.

        Raises ValueError (from the builder) if the aggregate has no history."""
        events = self._store.history(self._tenant_id, aggregate_id)
        raw_rows = self._store.raw_rows_for_tenant(self._tenant_id)
        return build_evidence_pack(events, raw_rows, outcome=outcome)

    def forecast(
        self,
        task: str,
        feature_row: dict,
        *,
        horizon_start: datetime,
        horizon_end: datetime,
        issued_at: datetime,
        interval_half_width: float | None = None,
        registry: "ModelRegistry",
        artifact_resolver: "Callable[[ModelVersion], str | Path]",
    ) -> "ForecastVintage":
        """Serve one point-in-time forecast for `task` from its champion model.

        `registry` and `artifact_resolver` are taken per call rather than held
        on the client: the canonical loop (ingest/decide/evidence) needs no ML
        infrastructure at all, so requiring a model registry + artifact resolver
        just to construct a client -- or to record a decision -- would couple the
        ten-minute `in_memory` path to xgboost and a model catalog it does not
        need. They are the same two dependencies `ForecastRuntime` itself is
        constructed from, threaded straight through. A caller making many
        forecasts and wanting the runtime's per-artifact load cache should hold a
        `ForecastRuntime` directly (this facade builds a fresh one per call).

        Demonstrated on real *aggregate* public data with a declared model
        interval -- `interval_half_width`, if given, is a symmetric model
        interval, not a probability or guarantee, and an aggregate forecast does
        not validate an individual dispatch (blueprint 01)."""
        # Lazy import: keeps xgboost/pandas off the SDK's import path for callers
        # that only drive the canonical loop.
        from packages.forecast import ForecastRuntime

        runtime = ForecastRuntime(registry, artifact_resolver)
        return runtime.forecast(
            task,
            feature_row,
            horizon_start=horizon_start,
            horizon_end=horizon_end,
            issued_at=issued_at,
            interval_half_width=interval_half_width,
        )

    def teardown_deadhead(
        self,
        segments: "Iterable[VehicleSegment]",
        *,
        dataset_label: str,
        data_provenance: "DataProvenance",
        run_ref_source: str,
        cost_basis: "CostBasis | None" = None,
        reduction_fraction: float = DEFAULT_REDUCTION_FRACTION,
        top_n_runs: int = 10,
        unmeasured_segments: int = 0,
        unmeasured_reason: str | None = None,
    ) -> "DeadheadTeardown":
        """Localise non-revenue ("empty") vehicle time to hours, days and runs,
        and value it at the operator's own cost per vehicle-hour.

        A straight pass-through to `packages.replay.teardown.teardown_deadhead`
        (ADR-0039): the facade adds no parameter of its own and REMOVES none, so
        every refusal that module encodes survives the SDK boundary unchanged --
        `CostBasis.avoidable_share_low/high` still have no default (absent them
        no envelope is produced and `envelope_basis` says why), there is still no
        way to ask for a guaranteed saving or causal proof, and `DataProvenance`
        still has no "operator" value.

        STATELESS: this reads nothing from, and writes nothing to, the canonical
        store. It is on the client because the client is the one import an
        integrator holds, not because a teardown is a stored artifact -- the
        result is a value the caller keeps or discards. If you want the teardown
        recorded as a decision, `record_decision` it explicitly.

        The result is a *modelled* localisation of where empty time sat -- never
        causal proof, never a promised saving (blueprint/01, ADR-0019).
        """
        return teardown_deadhead(
            segments,
            dataset_label=dataset_label,
            data_provenance=data_provenance,
            run_ref_source=run_ref_source,
            cost_basis=cost_basis,
            reduction_fraction=reduction_fraction,
            top_n_runs=top_n_runs,
            unmeasured_segments=unmeasured_segments,
            unmeasured_reason=unmeasured_reason,
        )

    def verify(self, aggregate_id: str) -> "tuple[ChainViolation, ...]":
        """Run the independent hash-chain verifier over this aggregate's raw
        stored rows. An empty tuple means the chain verified; any element is a
        detected violation. For the fuller multi-check integrity result (chain
        + schema), read `evidence_for(...).integrity_verified` instead."""
        raw_rows = self._store.raw_rows_for_tenant(self._tenant_id)
        relevant = [row for row in raw_rows if row.get("aggregate_id") == aggregate_id]
        return tuple(verify_chain(relevant))
