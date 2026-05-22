"""orchestrator/memory_embed.py

Ollama bge-m3 embedding helper for GossipBus.

Backported from oramasys/perpetua-core design spec to diazMelgarejo/Perpetua-Tools v1.
Reference: docs/superpowers/plans/2026-05-21-rag-memory-v1-plan.md Task 2 (embed.py)

Gap 1 fix (Antigravity Gemini 3.5 critique, 2026-05-21):
  probe_embed_dim() dynamically discovers the embedding model's output dimension
  by sending a dummy request to Ollama.  Previously the schema was hardcoded to
  1024 (bge-m3 default), causing schema/write mismatch errors if EMBED_MODEL
  was overridden to a model with different dimensions (e.g. nomic-embed-text=768).

Uses httpx (already a hard PT dependency — no new deps needed).
"""
from __future__ import annotations

import json
import os
from typing import Optional

import httpx


_OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
_EMBED_MODEL = os.environ.get("EMBED_MODEL", "bge-m3")

# Process-wide dim cache.  Re-probed if cleared (e.g. during testing).
_PROBED_DIM: Optional[int] = None


def probe_embed_dim() -> int:
    """Synchronous dim probe — call once at startup, result cached process-wide.

    Priority:
      1. EMBED_DIM env var (explicit override, testing / alternative models)
      2. Live Ollama probe via /api/embeddings with a dummy string
      3. Fallback 1024 (bge-m3 default — keeps system functional when Ollama is down)
    """
    global _PROBED_DIM
    if _PROBED_DIM is not None:
        return _PROBED_DIM

    env_dim = os.environ.get("EMBED_DIM")
    if env_dim:
        _PROBED_DIM = int(env_dim)
        return _PROBED_DIM

    try:
        response = httpx.post(
            f"{_OLLAMA_URL}/api/embeddings",
            json={"model": _EMBED_MODEL, "prompt": "probe"},
            timeout=5.0,
        )
        response.raise_for_status()
        data = response.json()
        _PROBED_DIM = len(data["embedding"])
        return _PROBED_DIM
    except Exception:
        _PROBED_DIM = 1024  # bge-m3 default
        return _PROBED_DIM


async def get_embedding(text: str) -> list[float]:
    """Return the Ollama bge-m3 embedding for *text*.

    Uses httpx async client (already a hard PT dependency).
    Raises on network/model error — callers should catch and mark embed_status='failed'.
    """
    model = os.environ.get("EMBED_MODEL", _EMBED_MODEL)
    base_url = os.environ.get("OLLAMA_BASE_URL", _OLLAMA_URL)

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{base_url}/api/embeddings",
            json={"model": model, "prompt": text},
        )
        resp.raise_for_status()
        return resp.json()["embedding"]
