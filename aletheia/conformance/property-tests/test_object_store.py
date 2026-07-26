"""Object-store conformance: a real round-trip against the running MinIO
container (talos/infra/compose), proving Program C's immutable object path works
end-to-end -- content-addressed keys, dedup, and read-time integrity.

Skips cleanly when the `minio` client isn't installed (the optional
`objectstore` extra) or the MinIO container isn't reachable, so the suite stays
green on CI and on a machine without the dev stack up.
"""

from __future__ import annotations

import pytest

minio = pytest.importorskip("minio")  # noqa: F841 -- skip whole module if extra absent

from themis.estate.object_store import (  # noqa: E402
    MinioObjectStore,
    ObjectStoreConfig,
    ObjectStoreError,
)


def _store_or_skip() -> MinioObjectStore:
    cfg = ObjectStoreConfig.from_compose_env()
    if not cfg.secret_key:
        pytest.skip("talos/infra/compose/.env not present -- MinIO dev stack not configured")
    try:
        return MinioObjectStore(cfg)
    except Exception as exc:  # noqa: BLE001 -- any connection failure => skip, not fail
        pytest.skip(f"MinIO not reachable ({type(exc).__name__}) -- dev stack not up")


def test_put_returns_sha256_key_and_get_round_trips() -> None:
    store = _store_or_skip()
    data = b"milexium object-store round-trip \xf0\x9f\x9a\x8c"  # includes a non-ascii byte run
    key = store.put(data)

    import hashlib

    assert key == hashlib.sha256(data).hexdigest()
    assert store.exists(key)
    assert store.get(key) == data


def test_put_is_deduplicated_by_content() -> None:
    store = _store_or_skip()
    data = b"same bytes, one object"
    assert store.put(data) == store.put(data)  # same key, second put is a no-op


def test_unknown_key_does_not_exist() -> None:
    store = _store_or_skip()
    assert not store.exists("0" * 64)


def test_get_detects_a_corrupted_object() -> None:
    """Put an object under a key that does NOT match its bytes (bypassing put's
    content-addressing) and prove get() rejects it on the sha256 re-check."""
    store = _store_or_skip()
    import io

    forged_key = "1" * 64
    store._client.put_object(store.bucket, forged_key, io.BytesIO(b"not matching"), length=12)
    with pytest.raises(ObjectStoreError, match="integrity failure"):
        store.get(forged_key)
