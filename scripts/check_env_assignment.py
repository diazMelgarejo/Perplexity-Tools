#!/usr/bin/env python3
"""
check_env_assignment.py

Pre-commit hook: reject whitespace-POST-fixed env assignments in all text files.

Syntax rule (per .claude/SKILL.md):
    FOO=value        ✓ valid
    FOO = value      ✗ rejected (whitespace before =)
    FOO= value      ✗ rejected (whitespace after = without before)
    FOO =value       ✗ rejected (whitespace both sides)

Pattern breakdown:
    ^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\S  → valid (no WS after =)
    ^([A-Za-z_][A-Za-z0-9_]*)\s*=\s+\S  → REJECTED (WS after =)
    ^([A-Za-z_][A-Za-z0-9_]*)\s+\S+\s*= → REJECTED (WS before =)

Inverted logic — flag lines that are invalid:
    ^([A-Za-z_][A-Za-z0-9_]*)\s+[A-Za-z_][A-Za-z0-9_]*\s*=  → WS before =
    ^([A-Za-z_][A-Za-z0-9_]*)\s*=\s+\S                        → WS after =

Usage (standalone or via pre-commit):
    python scripts/check_env_assignment.py [--quiet]
    python scripts/check_env_assignment.py file1 file2 ...

Exit codes:
    0  — no violations found
    1  — violations found (reported to stdout)
    2  — usage error
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Pattern 1: whitespace BEFORE the = sign (e.g. "FOO =value")
_WS_BEFORE_EQ = re.compile(r"^[A-Z_a-z][A-Za-z0-9_]*\s+=")

# Pattern 2: whitespace AFTER the = sign (e.g. "FOO= value" or "FOO = value")
_WS_AFTER_EQ = re.compile(r"^[A-Z_a-z][A-Za-z0-9_]*\s*=\s+\S")

# Patterns to skip (comments and intentionally blank lines)
_SKIP = re.compile(r"^\s*(#|$)")


def check_line(line: str, lineno: int, filename: str) -> list[str]:
    """Return list of error messages for a single line, empty if clean."""
    stripped = line.rstrip("\n")
    if _SKIP.match(stripped):
        return []
    errors = []
    if _WS_BEFORE_EQ.match(stripped):
        errors.append(
            f"{filename}:{lineno}: whitespace BEFORE '=' — "
            f"write FOO=value not 'FOO =value'"
        )
    if _WS_AFTER_EQ.match(stripped):
        errors.append(
            f"{filename}:{lineno}: whitespace AFTER '=' — "
            f"write FOO=value not 'FOO= value'"
        )
    return errors


def check_file(path: Path) -> list[str]:
    """Return all violations for a single file."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return [f"{path}: cannot read: {exc}"]
    errors = []
    for lineno, line in enumerate(content.splitlines(keepends=False), start=1):
        errors.extend(check_line(line, lineno, str(path)))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reject whitespace-POST-fixed env assignments in text files."
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true", help="Emit no output on success"
    )
    parser.add_argument(
        "files",
        nargs="*",
        metavar="FILE",
        help="Files to check (stdin if absent or '-')",
    )
    args = parser.parse_args(argv)

    all_errors: list[str] = []

    if not args.files or args.files == ["-"]:
        # Read from stdin (one filename per line — pre-commit passes filenames)
        for line in sys.stdin:
            path = Path(line.rstrip())
            if path.exists():
                all_errors.extend(check_file(path))
    else:
        for f in args.files:
            all_errors.extend(check_file(Path(f)))

    if not all_errors:
        if not args.quiet:
            print("check_env_assignment: no violations found")
        return 0

    for err in all_errors:
        print(err, file=sys.stderr)
    print(f"\ncheck_env_assignment: {len(all_errors)} violation(s) found", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
