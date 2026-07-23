"""MilexiumClient: the v0.1 facade over the canonical loop.

This module composes packages already in the repository -- it adds ergonomics
and one stable public surface, not new domain logic. Every method delegates:

- `in_memory` / tenant setup    -> packages.canonical.SqliteCanonicalStore
- `ingest`                      -> packages.connect.adapter.parse_batch
- `record_decision`/`_override` -> SqliteCanonicalStore.append_event
- `evidence_for`                -> packages.evidence.build_evidence_packet
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
from packages.evidence import build_evidence_packet
from packages.verify import verify_chain

if TYPE_CHECKING:
    from pydantic import BaseModel

    from packages.canonical import DecisionEvent, Outcome, ReasonCode
    from packages.connect.adapter import (
        QuarantinedRow,
        SemanticLossRecord,
        SourceAdapter,
    )
    from packages.evidence import EvidencePacket
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

    def verify(self, aggregate_id: str) -> "tuple[ChainViolation, ...]":
        """Run the independent hash-chain verifier over this aggregate's raw
        stored rows. An empty tuple means the chain verified; any element is a
        detected violation. For the fuller multi-check integrity result (chain
        + schema), read `evidence_for(...).integrity_verified` instead."""
        raw_rows = self._store.raw_rows_for_tenant(self._tenant_id)
        relevant = [row for row in raw_rows if row.get("aggregate_id") == aggregate_id]
        return tuple(verify_chain(relevant))
