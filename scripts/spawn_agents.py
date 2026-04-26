#!/usr/bin/env python3
"""
spawn_agents.py (PT mirror) — Parallel-agent dispatch.

This is a thin re-export shim so Perpetua-Tools scripts can launch agents
the same way as orama-system scripts.

The canonical implementation lives in orama-system/scripts/spawn_agents.py.
PT scripts/tests that need to dispatch agents should import from this module
(or call it from the CLI) — it delegates to the orama copy via sys.path if
orama-system is a sibling repo, otherwise it runs a self-contained version.

Usage (same as orama version):
    python scripts/spawn_agents.py --status
    python scripts/spawn_agents.py --task "review X" --agent codex
"""

from __future__ import annotations
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_PT_ROOT = _HERE.parents[1]
_ORAMA_SIBLING = _PT_ROOT.parent / "orama-system"
_ORAMA_SPAWN = _ORAMA_SIBLING / "scripts" / "spawn_agents.py"

if _ORAMA_SPAWN.exists():
    # Delegate: run orama's authoritative copy
    import importlib.util
    _spec = importlib.util.spec_from_file_location("spawn_agents", _ORAMA_SPAWN)
    assert _spec and _spec.loader
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
    # Re-export public API
    discover_agents = _mod.discover_agents  # type: ignore[attr-defined]
    dispatch = _mod.dispatch  # type: ignore[attr-defined]
    print_status = _mod.print_status  # type: ignore[attr-defined]
    if __name__ == "__main__":
        _mod.main()
else:
    # Fallback: self-contained stub (orama not present — typical in CI)
    import asyncio, argparse, json, shutil, subprocess, time
    from typing import Any, Dict, Optional

    def discover_agents():  # type: ignore[override]
        from dataclasses import dataclass

        @dataclass
        class _AI:
            name: str; kind: str; available: bool = False; version: str = ""; detail: str = ""

        codex_bin = shutil.which("codex") or "/opt/homebrew/bin/codex"
        ok = os.path.exists(codex_bin) and subprocess.run([codex_bin, "--version"], capture_output=True, timeout=4).returncode == 0
        return {"codex": _AI("Codex", "cli", ok, detail=codex_bin)}

    async def dispatch(agent: str, task: str, model: Optional[str] = None) -> Dict[str, Any]:
        codex_bin = shutil.which("codex") or "/opt/homebrew/bin/codex"
        if agent == "codex" and os.path.exists(codex_bin):
            proc = await asyncio.create_subprocess_exec(
                codex_bin, "--full-auto", task,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                cwd=str(_PT_ROOT),
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
            return {"ok": proc.returncode == 0, "output": stdout.decode("utf-8", errors="replace"), "elapsed": 0}
        return {"ok": False, "output": f"orama-system not found at {_ORAMA_SIBLING}; only 'codex' is available in PT standalone mode."}

    def print_status():
        agents = discover_agents()
        for k, ag in agents.items():
            print(f"  {'✓' if ag.available else '✗'}  {ag.name}  {ag.detail}")

    if __name__ == "__main__":
        import argparse as _ap
        p = _ap.ArgumentParser()
        p.add_argument("--task", "-t")
        p.add_argument("--agent", "-a", default="codex")
        p.add_argument("--status", "-s", action="store_true")
        p.add_argument("--json", dest="json_output", action="store_true")
        args = p.parse_args()
        if args.status:
            print_status()
        elif args.task:
            result = asyncio.run(dispatch(args.agent, args.task))
            if args.json_output:
                print(json.dumps(result, indent=2))
            else:
                print(result.get("output", ""))
            sys.exit(0 if result.get("ok") else 1)
