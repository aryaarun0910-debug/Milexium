"""Independent hash-chain verifier.

Reads raw stored rows (via `SqliteCanonicalStore.raw_rows_for_tenant`, which
bypasses the appender's own Pydantic reconstruction) and recomputes every
hash from scratch. It reuses `compute_hash`/`canonical_json` because those
*are* the normative contract (architecture/decisions/0003-...); what it does
not reuse is any bookkeeping from `HashChainAppender` or
`SqliteCanonicalStore.append_event` -- a bug in either of those would still
be caught here because this function repeats the computation independently
from raw bytes rather than trusting their internal state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from packages.canonical.events import compute_hash


@dataclass(frozen=True)
class ChainViolation:
    aggregate_id: str
    sequence: int
    kind: str  # "hash_mismatch" | "sequence_gap" | "prev_hash_mismatch" | "duplicate_sequence"
    detail: str


def verify_chain(raw_rows: list[dict]) -> list[ChainViolation]:
    """`raw_rows` need not be pre-sorted; this function groups and sorts them
    itself so it does not depend on the caller's (or the store's) ordering
    guarantee being correct.

    Returns an empty list iff every aggregate's chain is intact. Corruption is
    reported, never raised -- a verifier that only worked via exceptions
    could not enumerate *all* the problems in one pass.
    """
    violations: list[ChainViolation] = []
    by_aggregate: dict[str, list[dict]] = {}
    for row in raw_rows:
        by_aggregate.setdefault(row["aggregate_id"], []).append(row)

    for aggregate_id, rows in by_aggregate.items():
        rows = sorted(rows, key=lambda r: r["sequence"])
        expected_sequence = 1
        expected_prev_hash: str | None = None
        seen_sequences: set[int] = set()
        for row in rows:
            sequence = row["sequence"]
            if sequence in seen_sequences:
                violations.append(
                    ChainViolation(
                        aggregate_id, sequence, "duplicate_sequence",
                        f"sequence {sequence} appears more than once",
                    )
                )
                continue
            seen_sequences.add(sequence)

            if sequence != expected_sequence:
                violations.append(
                    ChainViolation(
                        aggregate_id, sequence, "sequence_gap",
                        f"expected sequence {expected_sequence}, found {sequence}",
                    )
                )

            if row["prev_hash"] != expected_prev_hash:
                violations.append(
                    ChainViolation(
                        aggregate_id, sequence, "prev_hash_mismatch",
                        f"expected prev_hash {expected_prev_hash!r}, found {row['prev_hash']!r}",
                    )
                )

            payload = json.loads(row["payload_json"])
            recomputed = compute_hash(
                row["prev_hash"], payload, sequence, aggregate_id, row.get("idempotency_key")
            )
            if recomputed != row["hash"]:
                violations.append(
                    ChainViolation(
                        aggregate_id, sequence, "hash_mismatch",
                        f"recomputed {recomputed} != stored {row['hash']}",
                    )
                )

            expected_sequence = sequence + 1
            expected_prev_hash = row["hash"]

    return violations
