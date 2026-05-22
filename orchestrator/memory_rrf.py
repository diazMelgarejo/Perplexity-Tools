"""orchestrator/memory_rrf.py

Reciprocal Rank Fusion (RRF) — merges FTS5 keyword hits and LanceDB vector
hits into a single ranked list.  Pure function; zero external dependencies.

Design decision (2026-05-21 RAG design, D_RRF-1):
  k=60 is the standard RRF constant from Cormack et al. (2009).
  Larger k compresses score differences; smaller k amplifies top-rank boost.
  60 has proven stable across retrieval benchmarks.

Backported from oramasys/perpetua-core design spec to diazMelgarejo/Perpetua-Tools v1.
Reference: docs/superpowers/plans/2026-05-21-rag-memory-v1-plan.md Task 2 (rrf.py)
"""
from __future__ import annotations

from uuid import uuid4


_RRF_K = 60  # standard constant; tunable if needed


def rrf_merge(
    fts_hits: list[dict],
    vec_hits: list[dict],
    *,
    k: int = _RRF_K,
    top_n: int = 5,
) -> list[dict]:
    """Merge two ranked hit lists via Reciprocal Rank Fusion.

    Args:
        fts_hits: BM25 keyword results from FTS5, ordered by rank (best first).
        vec_hits: ANN vector results from LanceDB, ordered by distance (best first).
        k:        RRF constant. Default 60 (standard).
        top_n:    Maximum items in returned list.

    Returns:
        Merged, deduplicated hit list sorted by descending RRF score.
        Falls back to fts_hits unchanged when vec_hits is empty, so FTS5-only
        mode requires no special handling at the call site.
    """
    if not vec_hits:
        return fts_hits[:top_n]

    scores: dict[str, float] = {}
    items: dict[str, dict] = {}

    def _key(hit: dict) -> str:
        """Stable string key for a hit.  row_id preferred; uuid fallback."""
        raw = hit.get("row_id")
        if raw is not None:
            return str(raw)
        # Items from vec store may not have row_id — assign a stable uuid
        return str(uuid4())

    for rank, hit in enumerate(fts_hits):
        key = _key(hit)
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        items.setdefault(key, hit)

    for rank, hit in enumerate(vec_hits):
        key = _key(hit)
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        items.setdefault(key, hit)

    ranked = sorted(scores.keys(), key=lambda k_: scores[k_], reverse=True)
    return [items[k] for k in ranked[:top_n]]
