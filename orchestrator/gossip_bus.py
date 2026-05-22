"""orchestrator/gossip_bus.py

GossipBus — lightweight aiosqlite event log with:
  - SQLite FTS5 BM25 keyword search (always available, zero deps)
  - Fire-and-forget Ollama bge-m3 embedding into LanceDB (optional; fails closed)
  - _pending_embeds GC guard (asyncio.create_task tasks held in module-level set)

Backported from oramasys/perpetua-core design spec to diazMelgarejo/Perpetua-Tools v1.
Reference: docs/superpowers/plans/2026-05-21-rag-memory-v1-plan.md Task 1

Design decisions recorded:
  D_GCG-1: Module-level _pending_embeds set prevents GC of in-flight asyncio tasks.
            asyncio.create_task() only holds a weak reference; without this guard
            the embedding is silently lost when the task object is collected.
  D_FTS-1: _sanitize_fts_query() strips FTS5 operators BEFORE calling MATCH.
            Real prompts contain quotes, colons, *, () — without sanitization
            the OperationalError silently drops ALL keyword recall for the query.
  D_EMB-1: embed_status column ('pending'|'embedded'|'failed') + index lets a
            future Reaper daemon efficiently find rows to retry without full scan.
  D_BPG-1: emit() never blocks on embed.  Cap _pending_embeds at 500 for
            backpressure; rows stay 'pending' and FTS5 fallback still works.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Literal, Optional

import aiosqlite


# ---------------------------------------------------------------------------
# GC guard (D_GCG-1)
# asyncio.get_running_loop() only holds a *weak* reference to tasks created
# with create_task().  This module-level set holds a *strong* reference so
# in-flight embedding tasks survive until their done-callback fires.
# ---------------------------------------------------------------------------
_pending_embeds: set[asyncio.Task] = set()

_MAX_PENDING = 500  # backpressure cap; keep small to avoid unbounded growth


# ---------------------------------------------------------------------------
# FTS5 schema DDL
# ---------------------------------------------------------------------------
_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS gossip (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           REAL    NOT NULL,
    event_type   TEXT    NOT NULL,
    payload_json TEXT    NOT NULL,
    embed_status TEXT    NOT NULL DEFAULT 'pending'
)
"""

_CREATE_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS gossip_fts
USING fts5(event_type, payload_json, content='gossip', content_rowid='id')
"""

_CREATE_FTS_AI = """
CREATE TRIGGER IF NOT EXISTS gossip_fts_ai
AFTER INSERT ON gossip BEGIN
  INSERT INTO gossip_fts(rowid, event_type, payload_json)
  VALUES (new.id, new.event_type, new.payload_json);
END
"""

_CREATE_FTS_AD = """
CREATE TRIGGER IF NOT EXISTS gossip_fts_ad
AFTER DELETE ON gossip BEGIN
  INSERT INTO gossip_fts(gossip_fts, rowid, event_type, payload_json)
  VALUES ('delete', old.id, old.event_type, old.payload_json);
END
"""

_CREATE_EMBED_IDX = """
CREATE INDEX IF NOT EXISTS idx_gossip_embed_status
ON gossip(embed_status) WHERE embed_status != 'embedded'
"""


# ---------------------------------------------------------------------------
# FTS5 query sanitizer (D_FTS-1 / Gap 2 fix from Antigravity Gemini 3.5 review)
# ---------------------------------------------------------------------------
# FTS5 reserved characters and operators that have special meaning in query syntax.
# See https://sqlite.org/fts5.html#fts5_strings
_FTS5_OPERATOR_RE = re.compile(r'[\"\':\*\+\-\(\)\[\]\{\}\^]')
_FTS5_KEYWORDS = {"AND", "OR", "NOT", "NEAR"}


def _sanitize_fts_query(query: str) -> str:
    """Strip FTS5 syntactic characters so MATCH treats input as plain terms.

    Quotes, colons, +/-/*, parens, and braces all have special meaning in
    FTS5 query syntax.  Real user prompts contain them constantly — without
    sanitization the entire keyword recall channel goes dark.  Reserved
    keywords (AND/OR/NOT/NEAR) are lowercased to remove their operator
    meaning; FTS5 only treats them as operators in uppercase.
    """
    if not query:
        return ""
    cleaned = _FTS5_OPERATOR_RE.sub(" ", query)
    tokens = [t.lower() if t in _FTS5_KEYWORDS else t for t in cleaned.split()]
    return " ".join(tokens).strip()


# ---------------------------------------------------------------------------
# GossipBus
# ---------------------------------------------------------------------------
EventType = Literal["dispatch", "route", "result", "error", "heartbeat"]


class GossipBus:
    """Append-only event log with FTS5 keyword search and optional LanceDB embeds.

    Usage:
        bus = GossipBus("perpetua_core.db")
        await bus.init_db()
        await bus.emit("dispatch", {"prompt": "summarize Q3 report"})
        hits = await bus.search("Q3 report")
    """

    def __init__(self, db_path: str = "perpetua_core.db"):
        self._db_path = db_path

    async def init_db(self) -> None:
        """Create schema idempotently.  Safe to call on every startup."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_CREATE_TABLE)
            # Idempotent column migration for pre-existing schemas
            try:
                await db.execute(
                    "ALTER TABLE gossip ADD COLUMN embed_status TEXT NOT NULL DEFAULT 'pending'"
                )
            except Exception:
                pass  # column already exists
            await db.execute(_CREATE_FTS)
            await db.execute(_CREATE_FTS_AI)
            await db.execute(_CREATE_FTS_AD)
            await db.execute(_CREATE_EMBED_IDX)
            await db.commit()
            # Backfill FTS index for pre-existing rows (idempotent)
            cursor = await db.execute("SELECT COUNT(*) FROM gossip_fts")
            (fts_count,) = await cursor.fetchone()
            cursor = await db.execute("SELECT COUNT(*) FROM gossip")
            (row_count,) = await cursor.fetchone()
            if row_count > 0 and fts_count == 0:
                await db.execute(
                    "INSERT INTO gossip_fts(rowid, event_type, payload_json) "
                    "SELECT id, event_type, payload_json FROM gossip"
                )
                await db.commit()

    async def emit(self, event_type: EventType, payload: dict) -> None:
        """Append an event and fire a non-blocking embed task.

        Never blocks on LanceDB / Ollama.  FTS5 is always synchronously written.
        """
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "INSERT INTO gossip (ts, event_type, payload_json, embed_status) "
                "VALUES (?, ?, ?, 'pending')",
                (time.time(), event_type, json.dumps(payload)),
            )
            row_id = cursor.lastrowid
            await db.commit()
        # Fire-and-forget embed — never blocks emit() return (D_BPG-1).
        # _pending_embeds holds a strong reference so GC cannot collect the task (D_GCG-1).
        if len(_pending_embeds) < _MAX_PENDING:
            task = asyncio.create_task(
                self._embed_and_store(row_id, payload),
                name=f"embed-{row_id}",
            )
            _pending_embeds.add(task)
            task.add_done_callback(_pending_embeds.discard)
        # else: backpressure — row stays 'pending'; FTS5 fallback still works

    async def tail(self, limit: int = 20, event_type: Optional[str] = None) -> list[dict]:
        """Return the most recent events, newest first."""
        async with aiosqlite.connect(self._db_path) as db:
            if event_type:
                cursor = await db.execute(
                    "SELECT id, ts, event_type, payload_json FROM gossip "
                    "WHERE event_type = ? ORDER BY id DESC LIMIT ?",
                    (event_type, limit),
                )
            else:
                cursor = await db.execute(
                    "SELECT id, ts, event_type, payload_json FROM gossip "
                    "ORDER BY id DESC LIMIT ?",
                    (limit,),
                )
            rows = await cursor.fetchall()
        return [
            {"row_id": r[0], "ts": r[1], "event_type": r[2], "payload": json.loads(r[3])}
            for r in rows
        ]

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        event_type: Optional[str] = None,
    ) -> list[dict]:
        """BM25 full-text search over GossipBus event history.  Always works.

        Sanitizes the query (strips FTS5 operators / quotes / colons) so real
        user prompts work without raising OperationalError.  The try/except
        around MATCH remains as defence-in-depth.
        """
        safe_query = _sanitize_fts_query(query)
        if not safe_query:
            return []
        try:
            async with aiosqlite.connect(self._db_path) as db:
                if event_type:
                    cursor = await db.execute(
                        """SELECT g.id, g.ts, g.event_type, g.payload_json
                           FROM gossip_fts f
                           JOIN gossip g ON g.id = f.rowid
                           WHERE gossip_fts MATCH ? AND g.event_type = ?
                           ORDER BY rank LIMIT ?""",
                        (safe_query, event_type, limit),
                    )
                else:
                    cursor = await db.execute(
                        """SELECT g.id, g.ts, g.event_type, g.payload_json
                           FROM gossip_fts f
                           JOIN gossip g ON g.id = f.rowid
                           WHERE gossip_fts MATCH ?
                           ORDER BY rank LIMIT ?""",
                        (safe_query, limit),
                    )
                rows = await cursor.fetchall()
            return [
                {"row_id": r[0], "ts": r[1], "event_type": r[2], "payload": json.loads(r[3])}
                for r in rows
            ]
        except Exception:
            return []  # defence-in-depth: FTS5 OperationalError → degrade gracefully

    # ------------------------------------------------------------------
    # Internal — embedding pipeline
    # ------------------------------------------------------------------

    async def _embed_and_store(self, row_id: int, payload: dict) -> None:
        """Embed payload via Ollama bge-m3 and persist to LanceDB (optional)."""
        try:
            from orchestrator.memory_embed import get_embedding  # noqa: PLC0415
            from orchestrator.memory_store import get_lance_store  # noqa: PLC0415

            text = json.dumps(payload)
            embedding = await get_embedding(text)
            store = get_lance_store()
            await store.add(row_id=row_id, text=text, embedding=embedding)
            await self._update_embed_status(row_id, "embedded")
        except Exception:
            await self._update_embed_status(row_id, "failed")

    async def _update_embed_status(self, row_id: int, status: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE gossip SET embed_status = ? WHERE id = ?",
                (status, row_id),
            )
            await db.commit()
