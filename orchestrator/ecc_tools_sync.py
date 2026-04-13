"""
orchestrator/ecc_tools_sync.py
------------------------------
Idempotent runtime sync of https://github.com/affaan-m/everything-claude-code

Runs at FastAPI startup and on-demand via POST /ecc/sync

Behaviour:
  1. Clone or `git pull` the ECC Tools repo into vendor/ecc-tools/
  2. Read .claude/ecc-tools.json to discover every managed file path
  3. For each file: compare SHA-256 of source vs destination;
     copy only when content differs (idempotent)
  4. Persist sync state to .state/ecc_sync.json
     (commit hash + per-file hashes + timestamp)
  5. On next run: skip files where hash already matches
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from loguru import logger
except ImportError:  # pragma: no cover - fallback for minimal environments
    logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ECC_REPO_URL: str = "https://github.com/affaan-m/everything-claude-code.git"
ECC_REPO_BRANCH: str = "main"

# Set ECC_SYNC_ENABLED=false to skip live git clone/pull at startup.
# Useful for offline deployments, CI environments, and unit test runs.
# Default: true (enabled — pulls latest ECC Tools on every startup).
ECC_SYNC_ENABLED: bool = os.getenv("ECC_SYNC_ENABLED", "true").lower() in ("true", "1", "yes")

# Vendor dir (cloned ECC Tools lives here, relative to project root)
VENDOR_DIR: Path = Path("vendor/ecc-tools")

# ECC manifest that lists all managed files
ECC_MANIFEST: Path = VENDOR_DIR / ".claude" / "ecc-tools.json"

# State file that records the last successful sync
STATE_FILE: Path = Path(".state/ecc_sync.json")

# Subfolder mapping:
# ECC paths are relative to the ECC repo root.
# We copy them verbatim into the Perplexity-Tools project root.
# Override specific paths here if destination should differ.
# Format: { "ecc/relative/path": "destination/relative/path" }
DESTINATION_OVERRIDES: dict[str, str] = {
    ".claude/skills/everything-claude-code/SKILL.md": (
        ".claude/skills/everything-claude-code/SKILL.md"
    ),
    ".agents/skills/everything-claude-code/SKILL.md": (
        ".agents/skills/everything-claude-code/SKILL.md"
    ),
    ".agents/skills/everything-claude-code/agents/openai.yaml": (
        ".agents/skills/everything-claude-code/agents/openai.yaml"
    ),
    ".claude/identity.json": ".claude/identity.json",
    ".codex/config.toml": ".codex/config.toml",
    ".codex/AGENTS.md": ".codex/AGENTS.md",
    ".codex/agents/explorer.toml": ".codex/agents/explorer.toml",
    ".codex/agents/reviewer.toml": ".codex/agents/reviewer.toml",
    ".codex/agents/docs-researcher.toml": ".codex/agents/docs-researcher.toml",
    ".claude/homunculus/instincts/inherited/everything-claude-code-instincts.yaml": (
        ".claude/homunculus/instincts/inherited/everything-claude-code-instincts.yaml"
    ),
    ".claude/rules/everything-claude-code-guardrails.md": (
        ".claude/rules/everything-claude-code-guardrails.md"
    ),
    ".claude/research/everything-claude-code-research-playbook.md": (
        ".claude/research/everything-claude-code-research-playbook.md"
    ),
    ".claude/team/everything-claude-code-team-config.json": (
        ".claude/team/everything-claude-code-team-config.json"
    ),
    ".claude/enterprise/controls.md": ".claude/enterprise/controls.md",
    ".claude/commands/database-migration.md": ".claude/commands/database-migration.md",
    ".claude/commands/feature-development.md": ".claude/commands/feature-development.md",
    ".claude/commands/add-language-rules.md": ".claude/commands/add-language-rules.md",
    ".claude/ecc-tools.json": ".claude/ecc-tools.json",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    """Return hex SHA-256 of a file, or empty string if missing."""
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_commit_hash(repo_dir: Path) -> str:
    """Return HEAD commit hash of a git repo, or '' on error."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _load_state() -> dict[str, Any]:
    """Load persisted sync state; return empty dict if missing."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Core sync steps
# ---------------------------------------------------------------------------


def _ensure_cloned() -> bool:
    """Ensure vendor/ecc-tools/ is cloned. Return True if available, False if unavailable."""
    VENDOR_DIR.parent.mkdir(parents=True, exist_ok=True)
    git_dir = VENDOR_DIR / ".git"

    if not git_dir.exists():
        logger.info(f"[ECC Sync] Cloning {ECC_REPO_URL} → {VENDOR_DIR}")
        result = subprocess.run(
            [
                "git",
                "clone",
                "--depth=1",
                "--branch",
                ECC_REPO_BRANCH,
                ECC_REPO_URL,
                str(VENDOR_DIR),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.error(f"[ECC Sync] Clone failed: {result.stderr}")
            return False  # unavailable
        logger.info("[ECC Sync] Clone complete.")
    return True  # available (just cloned or already existed)


def _pull_latest() -> tuple[str, str]:
    """Fetch latest from origin. Returns (old_hash, new_hash)."""
    old_hash = _git_commit_hash(VENDOR_DIR)
    logger.info(f"[ECC Sync] Pulling latest ECC Tools (current HEAD: {old_hash[:8]}...)")
    result = subprocess.run(
        ["git", "-C", str(VENDOR_DIR), "pull", "--ff-only", "origin", ECC_REPO_BRANCH],
        capture_output=True,
        text=True,
        timeout=8,   # Fail fast — ECC sync is non-fatal; 8 s is enough on any reachable network
    )
    if result.returncode != 0:
        logger.warning(f"[ECC Sync] git pull warning: {result.stderr.strip()}")
    new_hash = _git_commit_hash(VENDOR_DIR)
    return old_hash, new_hash


def _read_managed_files() -> list[str]:
    """Parse ecc-tools.json for managed file paths; fallback to DESTINATION_OVERRIDES."""
    if ECC_MANIFEST.exists():
        try:
            manifest = json.loads(ECC_MANIFEST.read_text(encoding="utf-8"))
            paths = manifest.get("managedFiles", [])
            if paths:
                return paths
        except Exception as e:
            logger.warning(f"[ECC Sync] Could not parse ecc-tools.json: {e}")
    logger.warning("[ECC Sync] Falling back to hardcoded DESTINATION_OVERRIDES list.")
    return list(DESTINATION_OVERRIDES.keys())


def _copy_files(
    managed_files: list[str],
    force: bool = False,
) -> dict[str, Any]:
    """Copy managed files from VENDOR_DIR to project root (hash-gated unless force)."""
    project_root = Path.cwd()
    results: dict[str, list] = {
        "copied": [],
        "skipped": [],
        "missing_source": [],
        "errors": [],
    }
    new_hashes: dict[str, str] = {}

    for ecc_rel_path in managed_files:
        src = VENDOR_DIR / ecc_rel_path
        dest_rel = DESTINATION_OVERRIDES.get(ecc_rel_path, ecc_rel_path)
        dest = project_root / dest_rel

        if not src.exists():
            logger.warning(f"[ECC Sync] Source missing: {src}")
            results["missing_source"].append(ecc_rel_path)
            continue

        src_hash = _sha256(src)
        dest_hash = _sha256(dest)
        new_hashes[ecc_rel_path] = src_hash

        if not force and src_hash == dest_hash:
            results["skipped"].append(ecc_rel_path)
            logger.debug(f"[ECC Sync] SKIP (unchanged): {dest_rel}")
            continue

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            action = "FORCE-COPY" if force else "COPY"
            logger.info(f"[ECC Sync] {action}: {ecc_rel_path} → {dest_rel}")
            results["copied"].append(ecc_rel_path)
        except Exception as e:
            logger.error(f"[ECC Sync] Error copying {ecc_rel_path}: {e}")
            results["errors"].append({"path": ecc_rel_path, "error": str(e)})

    return {**results, "file_hashes": new_hashes}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def sync_ecc_tools(force: bool = False) -> dict[str, Any]:
    """
    Full idempotent ECC Tools sync: clone/pull, hash-gated copy, persist .state/ecc_sync.json.
    """
    if not ECC_SYNC_ENABLED:
        logger.info("[ECC Sync] Skipped (ECC_SYNC_ENABLED=false)")
        return {"status": "skipped", "message": "ECC Tools sync disabled via ECC_SYNC_ENABLED"}
    state = _load_state()
    prev_commit = state.get("commit_hash", "")
    git_existed_before = (VENDOR_DIR / ".git").exists()
    vendor_available = _ensure_cloned()
    if not vendor_available:
        message = "ECC Tools vendor clone unavailable; sync skipped."
        logger.warning(f"[ECC Sync] {message}")
        return {
            "status": "error",
            "message": message,
            "vendor_dir": str(VENDOR_DIR),
            "commit_hash": "",
            "previous_commit_hash": prev_commit,
            "copied": [],
            "skipped_count": 0,
            "missing_source": [],
            "errors": [{"path": str(VENDOR_DIR), "error": "vendor clone unavailable"}],
        }
    just_cloned = not git_existed_before
    old_hash, new_hash = _pull_latest()
    commit_unchanged = (new_hash == prev_commit) and not just_cloned

    if commit_unchanged and not force:
        logger.info(
            f"[ECC Sync] Already up-to-date (HEAD={new_hash[:8]}). "
            "Skipping file copy. Pass force=true to override."
        )
        return {
            "status": "up_to_date",
            "commit_hash": new_hash,
            "message": "ECC Tools already at latest commit; no files changed.",
            "synced_at": state.get("synced_at", ""),
        }

    managed_files = _read_managed_files()
    copy_results = _copy_files(managed_files, force=force)

    now = datetime.now(timezone.utc).isoformat()
    new_state = {
        "commit_hash": new_hash,
        "previous_commit_hash": old_hash,
        "synced_at": now,
        "ecc_repo": ECC_REPO_URL,
        "ecc_branch": ECC_REPO_BRANCH,
        "file_hashes": copy_results["file_hashes"],
        "last_run_summary": {
            "copied": len(copy_results["copied"]),
            "skipped": len(copy_results["skipped"]),
            "missing_source": len(copy_results["missing_source"]),
            "errors": len(copy_results["errors"]),
        },
    }
    _save_state(new_state)

    summary = {
        "status": "synced",
        "commit_hash": new_hash,
        "previous_commit_hash": old_hash,
        "synced_at": now,
        "copied": copy_results["copied"],
        "skipped_count": len(copy_results["skipped"]),
        "missing_source": copy_results["missing_source"],
        "errors": copy_results["errors"],
        "message": (
            f"ECC Tools synced: {len(copy_results['copied'])} files updated, "
            f"{len(copy_results['skipped'])} unchanged."
        ),
    }
    logger.info(f"[ECC Sync] Done. {summary['message']}")
    return summary


def get_sync_status() -> dict[str, Any]:
    """Return last persisted sync state without running a sync."""
    state = _load_state()
    if not state:
        return {"status": "never_synced", "vendor_dir": str(VENDOR_DIR)}
    return {
        "status": "ok",
        "commit_hash": state.get("commit_hash", "unknown"),
        "synced_at": state.get("synced_at", "unknown"),
        "last_run_summary": state.get("last_run_summary", {}),
        "vendor_dir": str(VENDOR_DIR),
        "ecc_repo": ECC_REPO_URL,
    }
