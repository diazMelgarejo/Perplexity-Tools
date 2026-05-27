"""orchestrator/memory_store.py

LanceDB-backed vector store for GossipBus embeddings.

Backported from oramasys/perpetua-core design spec to diazMelgarejo/Perpetua-Tools v1.
Reference: docs/superpowers/plans/2026-05-21-rag-memory-v1-plan.md Task 2 (store.py)

Gap 1 fix (Antigravity Gemini 3.5 critique, 2026-05-21):
  EmbeddingStore.__init__ now accepts a ``dim`` parameter instead of hardcoding 1024.
  get_lance_store() resolves dim via: EMBED_DIM env var → probe_embed_dim() → 1024.
  Path-keyed singleton uses (db_path, dim) so model switches don't reuse a
  stale schema.

Design decisions:
  - Synchronous LanceDB calls are wrapped in run_in_executor to avoid blocking
    the event loop (LanceDB v0.6 is sync-only).
  - Table creation is guarded by an asyncio.Lock to prevent concurrent race.
  - Falls back to no-op / empty list if lancedb is not installed (optional dep).
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional


try:
    import lancedb
    import pyarrow as pa
    _LANCEDB_AVAILABLE = True
except ImportError:
    _LANCEDB_AVAILABLE = False


def lancedb_available() -> bool:
    """True when optional LanceDB deps are installed and vector search may run."""
    return _LANCEDB_AVAILABLE


# Path-keyed singleton: (db_path::dimN) → EmbeddingStore
# Keyed on both path AND dim to prevent schema mismatch if model changes.
_lance_stores: dict[str, "EmbeddingStore"] = {}


class EmbeddingStore:
    """Local LanceDB vector store.  Silently degrades if lancedb not installed.

    Gap 1 fix: ``dim`` is a constructor parameter, not hardcoded to 1024.
    Switching EMBED_MODEL from bge-m3 (1024-dim) to nomic-embed-text (768-dim)
    no longer causes a schema/write mismatch at the first ``add()`` call.
    """

    def __init__(self, db_path: str = "lance_memory.lance", *, dim: int = 1024):
        self._db_path = db_path
        self._dim = int(dim)
        self._table = None
        self._lock = asyncio.Lock()  # prevents concurrent _ensure_table() race

    def _get_schema(self):
        import pyarrow as pa  # noqa: PLC0415
        return pa.schema([
            pa.field("row_id", pa.int64()),
            pa.field("text", pa.utf8()),
            pa.field("vector", pa.list_(pa.float32(), self._dim)),
        ])

    def _ensure_table_sync(self):
        """Blocking table-open / create.  Called from run_in_executor."""
        if self._table is not None:
            return
        db = lancedb.connect(self._db_path)
        try:
            self._table = db.open_table("embeddings")
        except Exception:
            import pyarrow as pa  # noqa: PLC0415
            empty = pa.table(
                {
                    "row_id": pa.array([], type=pa.int64()),
                    "text": pa.array([], type=pa.utf8()),
                    "vector": pa.array(
                        [], type=pa.list_(pa.float32(), self._dim)
                    ),
                }
            )
            self._table = db.create_table("embeddings", data=empty)

    async def _ensure_table(self):
        async with self._lock:
            if self._table is None:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._ensure_table_sync)

    async def add(self, *, row_id: int, text: str, embedding: list[float]) -> None:
        """Persist one embedding row."""
        if not _LANCEDB_AVAILABLE:
            return
        await self._ensure_table()

        def _write():
            import pyarrow as pa  # noqa: PLC0415
            batch = pa.table(
                {
                    "row_id": pa.array([row_id], type=pa.int64()),
                    "text": pa.array([text], type=pa.utf8()),
                    "vector": pa.array(
                        [embedding], type=pa.list_(pa.float32(), self._dim)
                    ),
                }
            )
            self._table.add(batch)  # type: ignore[union-attr]

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _write)

    async def search(
        self,
        embedding: list[float],
        *,
        limit: int = 5,
    ) -> list[dict]:
        """ANN search.  Returns empty list if store is empty or unavailable."""
        if not _LANCEDB_AVAILABLE:
            return []
        try:
            await self._ensure_table()

            def _search():
                if self._table is None:
                    return []
                results = (
                    self._table.search(embedding)  # type: ignore[union-attr]
                    .limit(limit)
                    .to_list()
                )
                return results

            loop = asyncio.get_running_loop()
            rows = await loop.run_in_executor(None, _search)
            return [
                {"row_id": r["row_id"], "text": r["text"]}
                for r in (rows or [])
            ]
        except Exception:
            return []


def get_lance_store(
    db_path: str = "lance_memory.lance",
    *,
    dim: Optional[int] = None,
) -> EmbeddingStore:
    """Return a path+dim-keyed singleton EmbeddingStore.

    Dim resolution order (Gap 1 fix):
      1. Explicit ``dim`` argument
      2. EMBED_DIM environment variable
      3. probe_embed_dim() — live Ollama probe
      4. 1024 — bge-m3 default fallback
    """
    if dim is None:
        env_dim = os.environ.get("EMBED_DIM")
        if env_dim:
            dim = int(env_dim)
        else:
            try:
                from orchestrator.memory_embed import probe_embed_dim  # noqa: PLC0415
                dim = probe_embed_dim()
            except Exception:
                dim = 1024

    key = f"{db_path}::dim{dim}"
    if key not in _lance_stores:
        _lance_stores[key] = EmbeddingStore(db_path, dim=dim)
    return _lance_stores[key]
