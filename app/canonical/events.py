"""Append-only, hash-chained event log -- the "generator" side.

See knowledge/architecture/decisions/0003-append-only-hash-chained-event-log.md. This
module is the *only* thing that writes DecisionEvents. It deliberately does
not check its own output for tampering after the fact -- that is
app/verify's job, kept in a separate module so a bug shared between
"write" and "check" logic can't hide a real corruption (blueprint 19: "It
[the verifier swarm] owns the small trusted kernels and must be
organizationally separate from candidate generators.").
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from app.canonical.entities import DecisionEvent
from app.canonical.ids import DecisionEventId, TenantId, new_id
from app.canonical.vocab import DecisionEventType, ReasonCode

def canonical_json(payload: dict) -> str:
    """Deterministic JSON serialization: sorted keys, no incidental whitespace.

    The same logical payload must always hash the same way regardless of the
    dict insertion order a caller happened to build it in.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def compute_hash(
    prev_hash: str | None,
    payload: dict,
    sequence: int,
    aggregate_id: str,
    idempotency_key: str | None = None,
) -> str:
    """The normative hash function (knowledge/architecture/decisions/0003-...). Every
    implementation of the event log -- in-memory, SQLite, a future Postgres
    store -- must call this exact function with these exact arguments so
    hashes are comparable across implementations. `idempotency_key` is part
    of the hash (not folded into `payload`) so the user-visible payload never
    has to carry log-mechanics metadata.
    """
    digest = hashlib.sha256()
    digest.update((prev_hash or "").encode("utf-8"))
    digest.update(canonical_json(payload).encode("utf-8"))
    digest.update(str(sequence).encode("utf-8"))
    digest.update(aggregate_id.encode("utf-8"))
    digest.update((idempotency_key or "").encode("utf-8"))
    return digest.hexdigest()


class SequenceError(ValueError):
    """Raised when an append would create a gap or go backwards."""


class DuplicateEventError(ValueError):
    """Raised when an idempotency key repeats with a different payload."""


class HashChainAppender:
    """In-memory reference implementation of the append-only event log.

    `app/canonical/storage.py` provides a SQLite-backed store with the
    same `append`/`history` contract, exercised by the same conformance
    fixtures, so both implementations are checked against one behavioral
    contract rather than trusting either one by construction.
    """

    def __init__(self) -> None:
        self._chains: dict[tuple[TenantId, str], list[DecisionEvent]] = {}

    def append(
        self,
        *,
        tenant_id: TenantId,
        aggregate_id: str,
        aggregate_type: str,
        occurred_at: datetime,
        actor_type: str,
        actor_id: str,
        event_type: DecisionEventType,
        payload: dict,
        reason_codes: tuple[ReasonCode, ...] = (),
        idempotency_key: str | None = None,
    ) -> DecisionEvent:
        key = (tenant_id, aggregate_id)
        chain = self._chains.setdefault(key, [])

        if idempotency_key is not None:
            for existing in chain:
                if existing.idempotency_key == idempotency_key:
                    if existing.payload != payload:
                        raise DuplicateEventError(
                            f"idempotency key {idempotency_key!r} already used with a "
                            "different payload -- refusing to silently overwrite"
                        )
                    return existing  # idempotent replay: return the original, do not append again

        sequence = len(chain) + 1
        prev_hash = chain[-1].hash if chain else None
        event_hash = compute_hash(prev_hash, payload, sequence, aggregate_id, idempotency_key)
        event = DecisionEvent(
            event_id=new_id(DecisionEventId),
            tenant_id=tenant_id,
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            sequence=sequence,
            occurred_at=occurred_at,
            actor_type=actor_type,
            actor_id=actor_id,
            event_type=event_type,
            payload=payload,
            reason_codes=reason_codes,
            idempotency_key=idempotency_key,
            prev_hash=prev_hash,
            hash=event_hash,
        )
        chain.append(event)
        return event

    def history(self, tenant_id: TenantId, aggregate_id: str) -> tuple[DecisionEvent, ...]:
        return tuple(self._chains.get((tenant_id, aggregate_id), ()))

    def all_tenants(self) -> frozenset[TenantId]:
        return frozenset(tenant_id for tenant_id, _ in self._chains.keys())
