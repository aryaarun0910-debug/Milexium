"""SemanticIndex interface (knowledge/architecture/decisions/0005-semantic-index-interface.md).

One reference implementation, `ExactSearchIndex`, ships now: brute-force
cosine similarity in NumPy, the bounded-quality baseline every faster backend
(pgvector, TurboVec, DiskANN, HNSW -- all Specified, not Exists) must match
before it can be promoted, per the expansion's "every optimized
implementation retains an exact or bounded-quality reference and fallback."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np


class SemanticIndex(Protocol):
    def upsert(self, id: str, vector: np.ndarray, metadata: dict) -> None: ...

    def query(
        self, vector: np.ndarray, k: int, filters: dict | None = None
    ) -> list[tuple[str, float]]:
        """Returns up to `k` (id, similarity) pairs, highest similarity first."""
        ...

    def delete(self, id: str) -> None: ...

    def rebuild(self) -> None:
        """Derived indexes are rebuildable from canonical state -- this is a
        no-op for ExactSearchIndex (there is nothing to rebuild from, it *is*
        the ground truth) but a real ANN backend must implement it for real."""
        ...


@dataclass
class ExactSearchIndex:
    """Brute-force cosine-similarity reference implementation. O(n) per
    query on purpose -- correctness and auditability over speed, since this
    is the thing faster backends are benchmarked against, not a product path.
    """

    _vectors: dict[str, np.ndarray] = field(default_factory=dict)
    _metadata: dict[str, dict] = field(default_factory=dict)

    def upsert(self, id: str, vector: np.ndarray, metadata: dict) -> None:
        norm = np.linalg.norm(vector)
        if norm == 0:
            raise ValueError(f"cannot index a zero vector for id={id!r}")
        self._vectors[id] = vector / norm
        self._metadata[id] = metadata

    def query(
        self, vector: np.ndarray, k: int, filters: dict | None = None
    ) -> list[tuple[str, float]]:
        if k <= 0:
            raise ValueError("k must be positive")
        norm = np.linalg.norm(vector)
        if norm == 0:
            raise ValueError("cannot query with a zero vector")
        query_vec = vector / norm

        candidates = self._vectors.keys()
        if filters:
            candidates = [
                cid
                for cid in candidates
                if all(self._metadata[cid].get(fk) == fv for fk, fv in filters.items())
            ]

        scored = [(cid, float(np.dot(self._vectors[cid], query_vec))) for cid in candidates]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:k]

    def delete(self, id: str) -> None:
        self._vectors.pop(id, None)
        self._metadata.pop(id, None)

    def rebuild(self) -> None:
        return None
