#!/usr/bin/env python3
"""Pre-commit guard for model IDs known to be hallucinated in this system."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN = {"qwen3-coder-14b", "gemma4:e4b"}
ALLOWED_FILES_WITH_EXPLANATIONS = {".claude/skills/hardware-policy/SKILL.md"}
SCAN_SUFFIXES = {".py", ".json", ".yml", ".yaml", ".env", ".example", ".local"}
EXCLUDED_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}


def should_scan(path: Path) -> bool:
    rel_parts = set(path.relative_to(ROOT).parts)
    if rel_parts & EXCLUDED_DIRS:
        return False
    if path.name == Path(__file__).name:
        return False
    if str(path.relative_to(ROOT)) in ALLOWED_FILES_WITH_EXPLANATIONS:
        return False
    return path.suffix in SCAN_SUFFIXES or path.name.startswith(".env")


def main() -> int:
    violations: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or not should_scan(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        lower = text.lower()
        for forbidden in FORBIDDEN:
            if forbidden in lower:
                violations.append(f"{path.relative_to(ROOT)} contains hallucinated model ID: {forbidden}")
    if violations:
        print("\n".join(violations), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())