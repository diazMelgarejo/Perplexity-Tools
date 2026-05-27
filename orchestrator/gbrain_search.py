"""orchestrator/gbrain_search.py

Item 5 — GbrainSearch async helper (RAG v1 backport, 2026-05-27).

Calls the ``gbrain search`` CLI subprocess and returns keyword+semantic hits.
Always returns ``[]`` on any failure — never raises.  This is the v1 equivalent
of the v2 ``perpetua_core.sidecar.gstack.gbrain_query`` design (see
docs/v2/19-gstack-optional-integration.md § Detection contract).

Design constraints:
  - No ``@tool`` decorator (v1 has no tool registry).
  - No import-time side effects — gbrain CLI is probed at call time only.
  - Graceful degradation: subprocess missing, timeout, bad JSON, or any
    exception → return [].
  - Timeout: configurable via GBRAIN_SEARCH_TIMEOUT_SECONDS env var (default 5 s).

Backported from oramasys/* design spec to diazMelgarejo/Perpetua-Tools v1.
Reference: docs/superpowers/plans/2026-05-21-rag-memory-v1-plan.md (Item 5 note)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil

_log = logging.getLogger(__name__)

# Configurable via env; 5 s keeps this well under any LLM timeout.
_DEFAULT_TIMEOUT = float(os.environ.get("GBRAIN_SEARCH_TIMEOUT_SECONDS", "5"))


def _gbrain_binary() -> str | None:
    """Return the path to the gbrain binary, or None if not found."""
    return shutil.which("gbrain")


async def gbrain_search(
    query: str,
    *,
    limit: int = 5,
    timeout: float = _DEFAULT_TIMEOUT,
) -> list[dict]:
    """Call ``gbrain search <query>`` and return parsed hits.

    Args:
        query:   Search query string.
        limit:   Maximum number of results to request (``--limit`` flag).
        timeout: Subprocess timeout in seconds.

    Returns:
        List of dicts with at least a ``text`` key.  Empty list on any failure.
    """
    if not query or not query.strip():
        return []

    gbrain = _gbrain_binary()
    if gbrain is None:
        _log.debug("gbrain_search: gbrain binary not found on PATH; skipping")
        return []

    cmd = [gbrain, "search", query.strip(), "--limit", str(limit), "--json"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            _log.debug("gbrain_search: subprocess timed out after %.1f s", timeout)
            return []

        if proc.returncode != 0:
            _log.debug(
                "gbrain_search: exit %d — %s",
                proc.returncode,
                stderr.decode(errors="replace").strip()[:200],
            )
            return []

        raw = stdout.decode(errors="replace").strip()
        if not raw:
            return []

        data = json.loads(raw)
        # gbrain --json may return a list directly or {"results": [...]}
        if isinstance(data, list):
            hits = data
        elif isinstance(data, dict):
            hits = data.get("results", data.get("hits", []))
        else:
            return []

        return _normalise_hits(hits, limit)

    except json.JSONDecodeError as exc:
        _log.debug("gbrain_search: JSON parse error — %s", exc)
        return []
    except Exception as exc:  # pragma: no cover — broad safety net
        _log.debug("gbrain_search: unexpected error — %s", exc)
        return []


def _normalise_hits(raw_hits: list, limit: int) -> list[dict]:
    """Normalise gbrain output to [{text: str, ...}] dicts."""
    out: list[dict] = []
    for item in raw_hits[:limit]:
        if not isinstance(item, dict):
            continue
        # gbrain may return {content, title, score, ...} — map to {text, ...}
        text = (
            item.get("content")
            or item.get("text")
            or item.get("title")
            or ""
        )
        if text:
            out.append({"text": str(text), **{
                k: v for k, v in item.items() if k not in ("content", "text")
            }})
    return out
