"""tests/test_memory_store.py

Tests for orchestrator/memory_store.py — LanceDB EmbeddingStore.
Skips if lancedb is not installed (optional dependency).
Tests dim parameterization and probe_embed_dim resolution (Gap 1 fix).
"""
from __future__ import annotations

import os
import pytest


lancedb = pytest.importorskip("lancedb", reason="lancedb not installed — skipping vector store tests")


from orchestrator.memory_store import EmbeddingStore, get_lance_store, _lance_stores


@pytest.fixture(autouse=True)
def clear_store_singletons():
    """Ensure no cross-test leakage in the path-keyed singleton dict."""
    _lance_stores.clear()
    yield
    _lance_stores.clear()


@pytest.mark.asyncio
async def test_store_add_and_search(tmp_path):
    """Add a row, search for it by embedding."""
    store = EmbeddingStore(str(tmp_path / "test.lance"), dim=4)
    embedding = [0.1, 0.2, 0.3, 0.4]
    await store.add(row_id=1, text="blue widget task", embedding=embedding)
    results = await store.search(embedding, limit=5)
    assert len(results) >= 1
    assert results[0]["row_id"] == 1


@pytest.mark.asyncio
async def test_store_search_empty_returns_empty(tmp_path):
    """Search on empty store returns empty list."""
    store = EmbeddingStore(str(tmp_path / "empty.lance"), dim=4)
    results = await store.search([0.0, 0.0, 0.0, 0.0], limit=5)
    assert results == []


@pytest.mark.asyncio
async def test_store_search_never_raises(tmp_path):
    """Malformed embedding → empty list, no exception."""
    store = EmbeddingStore(str(tmp_path / "bad.lance"), dim=4)
    try:
        results = await store.search([], limit=5)
        assert isinstance(results, list)
    except Exception as e:
        pytest.fail(f"store.search raised: {e}")


# ---------------------------------------------------------------------------
# Gap 1: dim parameterization via get_lance_store + EMBED_DIM env var
# ---------------------------------------------------------------------------

def test_get_lance_store_env_dim(tmp_path, monkeypatch):
    """EMBED_DIM env var controls the store dimension."""
    monkeypatch.setenv("EMBED_DIM", "768")
    store = get_lance_store(str(tmp_path / "env.lance"))
    assert store._dim == 768


def test_get_lance_store_explicit_dim(tmp_path):
    """Explicit dim kwarg takes highest priority."""
    store = get_lance_store(str(tmp_path / "explicit.lance"), dim=384)
    assert store._dim == 384


def test_get_lance_store_returns_singleton(tmp_path):
    """Same path+dim returns same object."""
    path = str(tmp_path / "singleton.lance")
    s1 = get_lance_store(path, dim=16)
    s2 = get_lance_store(path, dim=16)
    assert s1 is s2


def test_get_lance_store_different_dims_are_different(tmp_path):
    """Different dims → different singletons (schema isolation)."""
    path = str(tmp_path / "multi.lance")
    s1024 = get_lance_store(path, dim=1024)
    s768 = get_lance_store(path, dim=768)
    assert s1024 is not s768
