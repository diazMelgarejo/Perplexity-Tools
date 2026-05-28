#!/usr/bin/env python3
"""Repo hygiene guard for Perpetua-Tools.

Checks run in CI and as a pre-commit gate. Mirrors the equivalent script in
orama-system/scripts/review/repo_hygiene.py — keep constants in sync.
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
import sys
from pathlib import Path


APPROVED_IDENTITIES = {
    ("cyre", "Lawrence@cyre.me"),
    ("cyre", "diazMelgarejo@gmail.com"),
    ("Codex", "codex@openai.com"),
}
# Keep in sync with scripts/git/check_identity.sh (local hooks + pre-commit).
FORBIDDEN_TOKENS = (
    "Lawrence " + "Melgarejo",
    "Lawrence" + "@bettermind.ph",
)
IDENTITY_DOC_EXCEPTIONS: set[str] = {
    ".mailmap",
}
# Personal-path leak protection (OpSec) — block any tracked file from containing
# an absolute path under /Users/<anything>/ or /home/<anything>/. Developer
# workstation paths in public docs are a dox risk and hurt portability.
# Use ~, $REPO_ROOT, or <workspace> instead.
PERSONAL_PATH_PATTERN = re.compile(r"(/Users/|/home/)([A-Za-z][A-Za-z0-9._-]+)/")
# Username segments that are documentation placeholders, not real leaks.
PERSONAL_PATH_PLACEHOLDERS = frozenset({
    "you", "user", "example", "username", "name", "youruser", "yourname",
    "<user>", "<username>", "USERNAME", "USER",
})
PERSONAL_PATH_EXCEPTIONS = {
    # The script itself names the pattern in source as documentation.
    "scripts/review/repo_hygiene.py",
    # Hygiene test asserts the rule against fixture content.
    "tests/test_repo_hygiene.py",
}
# Hidden / bidirectional Unicode controls — Trojan-Source defense (CVE-2021-42574).
# These can hide malicious code in diffs. Block in all tracked files except the
# hygiene script and its tests, which name the codepoints for documentation.
BIDI_CONTROL_CHARS = {
    "‪": "LRE", "‫": "RLE", "‬": "PDF",
    "‭": "LRO", "‮": "RLO",
    "⁦": "LRI", "⁧": "RLI", "⁨": "FSI", "⁩": "PDI",
}
BIDI_CONTROL_EXCEPTIONS = {
    "scripts/review/repo_hygiene.py",
    "tests/test_repo_hygiene.py",
}
PRIVATE_GENERATED_TRACKED = {".env", ".env.local", ".paths"}
# Paths exempt from GENERATED_ARTIFACT_PATTERNS.
# Use sparingly — only for intentionally committed compiled outputs that are
# required for distribution without a build step (e.g., npm MCP packages).
GENERATED_ARTIFACT_EXCEPTIONS: frozenset[str] = frozenset({
    # alphaclaw-mcp pre-built JS — committed so the MCP server installs without
    # requiring `npm run build`. Keep this entry as long as the package is
    # distributed as a pre-built artifact.
    "packages/alphaclaw-mcp/build/index.js",
    "packages/alphaclaw-mcp/build/is-direct-execution.js",
})

GENERATED_ARTIFACT_PATTERNS = (
    ".DS_Store",
    "*/.DS_Store",
    "._*",
    "*/._*",
    "__pycache__/*",
    "*/__pycache__/*",
    "*.pyc",
    "*.pyo",
    ".pytest_cache/*",
    "*/.pytest_cache/*",
    ".mypy_cache/*",
    "*/.mypy_cache/*",
    "dist/*",
    "*/dist/*",
    "build/*",
    "*/build/*",
    "DerivedData/*",
    "*/DerivedData/*",
    "*.egg-info/*",
    "*.whl",
    "*.tar.gz",
    "*.xcuserstate",
    "*.xcscmblueprint",
    "*.xcodeproj/xcuserdata/*",
    "*.xcworkspace/xcuserdata/*",
    "*.xcuserdatad/*",
)
WORKFLOW_WRITE_MARKERS = (
    "softprops/action-gh-release",
    "peter-evans/create-pull-request",
    "gh pr",
    "gh release",
    "git push",
)


def run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def tracked_files(root: Path) -> list[str]:
    proc = run_git(root, "ls-files")
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git ls-files failed")
    return [line for line in proc.stdout.splitlines() if line]


def is_binary(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:4096]
    except OSError:
        return True
    return b"\0" in chunk


def scan_forbidden_identity(root: Path, files: list[str]) -> list[str]:
    errors: list[str] = []
    for rel in files:
        if rel in IDENTITY_DOC_EXCEPTIONS:
            continue
        path = root / rel
        if not path.is_file() or is_binary(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for token in FORBIDDEN_TOKENS:
            if token in text:
                errors.append(f"forbidden identity token in tracked file: {rel}")
                break
    return errors


def scan_personal_paths(root: Path, files: list[str]) -> list[str]:
    """Block absolute /Users/<name>/ or /home/<name>/ paths in tracked files.

    Workstation paths in committed files are an OpSec leak (developer name,
    directory layout, sometimes machine hostname). They also break portability.
    Use ~, $REPO_ROOT, or <workspace> placeholders instead.
    """
    errors: list[str] = []
    for rel in files:
        if rel in PERSONAL_PATH_EXCEPTIONS:
            continue
        path = root / rel
        if not path.is_file() or is_binary(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            m = PERSONAL_PATH_PATTERN.search(line)
            if not m:
                continue
            username = m.group(2)
            if username in PERSONAL_PATH_PLACEHOLDERS:
                continue
            errors.append(
                f"personal absolute path in tracked file: {rel}:{line_no}: "
                f"matched {m.group(0)!r} — use ~, $REPO_ROOT, or <workspace>"
            )
            break
    return errors


def scan_bidi_controls(root: Path, files: list[str]) -> list[str]:
    """Block Unicode BiDi control characters (Trojan-Source defense).

    These invisible characters can reorder source code so the rendered
    text differs from the parsed AST. CVE-2021-42574.
    """
    errors: list[str] = []
    for rel in files:
        if rel in BIDI_CONTROL_EXCEPTIONS:
            continue
        path = root / rel
        if not path.is_file() or is_binary(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            for ch, name in BIDI_CONTROL_CHARS.items():
                if ch in line:
                    errors.append(
                        f"BiDi control char in tracked file: {rel}:{line_no}: "
                        f"U+{ord(ch):04X} ({name})"
                    )
                    break
            else:
                continue
            break
    return errors


def check_private_generated_tracking(files: list[str]) -> list[str]:
    return [
        f"private/generated config is tracked: {rel}"
        for rel in files
        if rel in PRIVATE_GENERATED_TRACKED
    ]


def check_generated_artifact_tracking(files: list[str]) -> list[str]:
    errors: list[str] = []
    for rel in files:
        if rel in GENERATED_ARTIFACT_EXCEPTIONS:
            continue
        if any(fnmatch.fnmatch(rel, pattern) for pattern in GENERATED_ARTIFACT_PATTERNS):
            errors.append(f"generated artifact is tracked: {rel}")
    return errors


def check_git_internal_junk(root: Path) -> list[str]:
    git_dir = root / ".git"
    refs_dir = git_dir / "refs"
    if not refs_dir.exists():
        return []
    return [
        f"macOS metadata file inside git refs: {path.relative_to(root)}"
        for path in refs_dir.rglob(".DS_Store")
    ]


def check_identity(root: Path) -> list[str]:
    name = run_git(root, "config", "user.name").stdout.strip()
    email = run_git(root, "config", "user.email").stdout.strip()
    if os.getenv("GITHUB_ACTIONS") == "true" and not name and not email:
        return []
    if (name, email) not in APPROVED_IDENTITIES:
        expected = " or ".join(f"{n} <{e}>" for n, e in sorted(APPROVED_IDENTITIES))
        return [
            "git identity mismatch: "
            f"found {name or '<unset>'} <{email or '<unset>'}>; "
            f"expected {expected}"
        ]
    return []


def check_workflow_permissions(root: Path) -> list[str]:
    errors: list[str] = []
    workflow_dir = root / ".github" / "workflows"
    if not workflow_dir.exists():
        return errors
    for path in sorted(workflow_dir.glob("*.y*ml")):
        text = path.read_text(encoding="utf-8")
        needs_write = any(marker in text for marker in WORKFLOW_WRITE_MARKERS)
        if not needs_write:
            continue
        rel = path.relative_to(root)
        if "contents: write" not in text and "pull-requests: write" not in text:
            errors.append(f"workflow may write but lacks explicit write permission: {rel}")
    return errors


def report_status(root: Path) -> list[str]:
    warnings: list[str] = []
    status = run_git(root, "status", "--short", "--branch")
    if status.returncode != 0:
        return [f"git status failed: {status.stderr.strip()}"]
    warnings.append(status.stdout.strip())
    shallow = run_git(root, "rev-parse", "--is-shallow-repository")
    if shallow.returncode == 0:
        warnings.append(f"shallow={shallow.stdout.strip()}")
    return warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Repo hygiene guard for Perpetua-Tools")
    parser.add_argument("repo", nargs="?", default=".", help="repository root")
    args = parser.parse_args()

    root = Path(args.repo).resolve()
    files = tracked_files(root)

    errors: list[str] = []
    errors.extend(check_identity(root))
    errors.extend(scan_forbidden_identity(root, files))
    errors.extend(scan_personal_paths(root, files))
    errors.extend(scan_bidi_controls(root, files))
    errors.extend(check_private_generated_tracking(files))
    errors.extend(check_generated_artifact_tracking(files))
    errors.extend(check_git_internal_junk(root))
    errors.extend(check_workflow_permissions(root))

    for line in report_status(root):
        print(f"INFO: {line}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print("OK: repo hygiene checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
