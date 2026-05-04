#!/usr/bin/env python3
"""Reject invalid shell-style env assignments in *.env* files.

Blocks lines like `FOO =bar` or `FOO= bar` in tracked env files.
Comments and blank lines are ignored.
"""
from __future__ import annotations
import re
import subprocess
import sys

BAD = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s+=\s*.*$")


def tracked_env_files() -> list[str]:
    out = subprocess.check_output(["git", "ls-files"], text=True)
    files = []
    for p in out.splitlines():
        name = p.split("/")[-1]
        if name.startswith('.env'):
            files.append(p)
    return files


def main() -> int:
    bad: list[str] = []
    for path in tracked_env_files():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for i, line in enumerate(f, 1):
                    s = line.rstrip('\n')
                    if not s.strip() or s.lstrip().startswith('#'):
                        continue
                    if BAD.match(s):
                        bad.append(f"{path}:{i}: {s}")
        except FileNotFoundError:
            continue

    if bad:
        print("❌ Invalid env assignment syntax found (remove spaces around '='):")
        for b in bad:
            print(f"  - {b}")
        return 1
    print("✅ Env assignment syntax check passed.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
