"""Env gate for subprocess-spawning CLI workers (security fix 6).

Codex, Gemini, and Antigravity (agy) workers spawn external CLIs with permission
bypass flags. They are disabled unless explicitly opted in.

Set PT_ALLOW_DANGEROUS_CLI_WORKERS=1 (or true/yes/on) on the control plane host.
"""
from __future__ import annotations

import os

DANGEROUS_CLI_BACKENDS = frozenset({"codex", "gemini", "agy"})


def dangerous_cli_workers_enabled() -> bool:
    v = (os.environ.get("PT_ALLOW_DANGEROUS_CLI_WORKERS") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def assert_dangerous_cli_worker_allowed(backend: str) -> None:
    if backend not in DANGEROUS_CLI_BACKENDS:
        return
    if dangerous_cli_workers_enabled():
        return
    raise RuntimeError(
        f"CLI subprocess worker '{backend}' is disabled. "
        "Set PT_ALLOW_DANGEROUS_CLI_WORKERS=1 on the orchestrator to enable "
        "codex/gemini/agy workers."
    )
