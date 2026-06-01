"""Tests for scripts/review/repo_hygiene.py — Perpetua-Tools hygiene gate.

Mirrors orama-system/tests/test_repo_hygiene.py with PT-specific adaptations.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parent.parent
HYGIENE_PATH = ROOT / "scripts" / "review" / "repo_hygiene.py"


def load_repo_hygiene():
    spec = importlib.util.spec_from_file_location("repo_hygiene", HYGIENE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# scan_personal_paths
# ---------------------------------------------------------------------------

def test_personal_path_real_username_is_blocked(tmp_path):
    repo_hygiene = load_repo_hygiene()
    doc = tmp_path / "README.md"
    doc.write_text("Run: /Users/johndoe/projects/pt/start.sh\n", encoding="utf-8")

    errors = repo_hygiene.scan_personal_paths(tmp_path, ["README.md"])

    assert len(errors) == 1
    assert "README.md:1" in errors[0]
    assert "/Users/johndoe/" in errors[0]


def test_personal_path_home_is_blocked(tmp_path):
    repo_hygiene = load_repo_hygiene()
    doc = tmp_path / "docs" / "setup.md"
    doc.parent.mkdir()
    doc.write_text("cd /home/johndoe/code/pt\n", encoding="utf-8")

    errors = repo_hygiene.scan_personal_paths(tmp_path, ["docs/setup.md"])

    assert len(errors) == 1
    assert "/home/johndoe/" in errors[0]


def test_personal_path_placeholder_usernames_are_allowed(tmp_path):
    repo_hygiene = load_repo_hygiene()
    doc = tmp_path / "docs" / "install.md"
    doc.parent.mkdir()
    doc.write_text(
        "Example: /Users/you/projects/pt\n"
        "Or: /home/user/code\n"
        "Or: /Users/username/pt\n"
        "Or: /Users/example/dir\n",
        encoding="utf-8",
    )

    errors = repo_hygiene.scan_personal_paths(tmp_path, ["docs/install.md"])

    assert errors == [], f"Placeholder usernames should be allowed: {errors}"


def test_personal_path_script_self_is_exempt(tmp_path):
    """The hygiene script itself is exempt (it names the pattern for documentation)."""
    repo_hygiene = load_repo_hygiene()
    script = tmp_path / "scripts" / "review" / "repo_hygiene.py"
    script.parent.mkdir(parents=True)
    script.write_text("/Users/realuser/something\n", encoding="utf-8")

    errors = repo_hygiene.scan_personal_paths(
        tmp_path, ["scripts/review/repo_hygiene.py"]
    )

    assert errors == []


def test_personal_path_test_file_is_exempt(tmp_path):
    """The test file itself is exempt (it uses fixture personal paths)."""
    repo_hygiene = load_repo_hygiene()
    test_file = tmp_path / "tests" / "test_repo_hygiene.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("/Users/realuser/fixture\n", encoding="utf-8")

    errors = repo_hygiene.scan_personal_paths(
        tmp_path, ["tests/test_repo_hygiene.py"]
    )

    assert errors == []


def test_personal_path_clean_file_passes(tmp_path):
    repo_hygiene = load_repo_hygiene()
    doc = tmp_path / "README.md"
    doc.write_text(
        "Run from: ~/projects/pt\n"
        "Or set REPO_ROOT and use $REPO_ROOT/start.sh\n",
        encoding="utf-8",
    )

    errors = repo_hygiene.scan_personal_paths(tmp_path, ["README.md"])

    assert errors == []


# ---------------------------------------------------------------------------
# scan_bidi_controls
# ---------------------------------------------------------------------------

# Actual BiDi control characters used as test fixtures (permitted in this file
# because "tests/test_repo_hygiene.py" is in BIDI_CONTROL_EXCEPTIONS).
_LRE = "‪"  # Left-to-Right Embedding
_RLO = "‮"  # Right-to-Left Override
_LRI = "⁦"  # Left-to-Right Isolate
_PDI = "⁩"  # Pop Directional Isolate


def test_bidi_lre_is_blocked(tmp_path):
    repo_hygiene = load_repo_hygiene()
    src = tmp_path / "orchestrator" / "agent.py"
    src.parent.mkdir()
    src.write_text(f"# {_LRE}access_level = 'user'\n", encoding="utf-8")

    errors = repo_hygiene.scan_bidi_controls(tmp_path, ["orchestrator/agent.py"])

    assert len(errors) == 1
    assert "U+202A" in errors[0]
    assert "LRE" in errors[0]


def test_bidi_rlo_is_blocked(tmp_path):
    repo_hygiene = load_repo_hygiene()
    src = tmp_path / "config.py"
    src.write_text(f"key = {_RLO}value\n", encoding="utf-8")

    errors = repo_hygiene.scan_bidi_controls(tmp_path, ["config.py"])

    assert len(errors) == 1
    assert "U+202E" in errors[0]
    assert "RLO" in errors[0]


def test_bidi_multiple_chars_report_first_per_file(tmp_path):
    """Only first BiDi char per file is reported (break-after-first logic)."""
    repo_hygiene = load_repo_hygiene()
    src = tmp_path / "evil.py"
    src.write_text(
        f"line1 = {_LRE}ok\n"
        f"line2 = {_RLO}bad\n",
        encoding="utf-8",
    )

    errors = repo_hygiene.scan_bidi_controls(tmp_path, ["evil.py"])

    assert len(errors) == 1  # only first char/line triggers, then breaks


def test_bidi_clean_file_passes(tmp_path):
    repo_hygiene = load_repo_hygiene()
    src = tmp_path / "clean.py"
    src.write_text("def hello():\n    return 'world'\n", encoding="utf-8")

    errors = repo_hygiene.scan_bidi_controls(tmp_path, ["clean.py"])

    assert errors == []


def test_bidi_exceptions_are_exempt(tmp_path):
    """The hygiene script and test file are exempt from BiDi scanning."""
    repo_hygiene = load_repo_hygiene()
    script = tmp_path / "scripts" / "review" / "repo_hygiene.py"
    script.parent.mkdir(parents=True)
    script.write_text(f"BIDI_LRE = '{_LRE}'\n", encoding="utf-8")

    test_file = tmp_path / "tests" / "test_repo_hygiene.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(f"_LRE = '{_LRE}'\n", encoding="utf-8")

    errors = repo_hygiene.scan_bidi_controls(
        tmp_path,
        ["scripts/review/repo_hygiene.py", "tests/test_repo_hygiene.py"],
    )

    assert errors == []


# ---------------------------------------------------------------------------
# generated artifact tracking
# ---------------------------------------------------------------------------

def test_generated_artifact_patterns_are_blocked():
    repo_hygiene = load_repo_hygiene()
    errors = repo_hygiene.check_generated_artifact_tracking(
        [
            ".DS_Store",
            "orchestrator/__pycache__/contracts.cpython-312.pyc",
            "dist/perpetua_tools-0.9.9.9.whl",
            "README.md",
        ]
    )

    assert "generated artifact is tracked: .DS_Store" in errors
    assert "generated artifact is tracked: orchestrator/__pycache__/contracts.cpython-312.pyc" in errors
    assert "generated artifact is tracked: dist/perpetua_tools-0.9.9.9.whl" in errors
    assert not any("README.md" in e for e in errors)


# ---------------------------------------------------------------------------
# private generated config
# ---------------------------------------------------------------------------

def test_private_generated_configs_are_blocked():
    repo_hygiene = load_repo_hygiene()
    errors = repo_hygiene.check_private_generated_tracking(
        [".env", ".env.local", ".paths", "README.md"]
    )

    assert "private/generated config is tracked: .env" in errors
    assert "private/generated config is tracked: .env.local" in errors
    assert not any("README.md" in e for e in errors)


# ---------------------------------------------------------------------------
# scan_forbidden_identity
# ---------------------------------------------------------------------------

def test_forbidden_identity_token_is_blocked(tmp_path):
    repo_hygiene = load_repo_hygiene()
    doc = tmp_path / "notes.md"
    # Build token at runtime to avoid triggering the hygiene scan on THIS file.
    token = "Lawrence " + "Melgarejo"
    doc.write_text(f"Author: {token}\n", encoding="utf-8")

    errors = repo_hygiene.scan_forbidden_identity(tmp_path, ["notes.md"])

    assert len(errors) == 1
    assert "notes.md" in errors[0]


def test_forbidden_identity_exception_is_exempt(tmp_path):
    repo_hygiene = load_repo_hygiene()
    mailmap = tmp_path / ".mailmap"
    token = "Lawrence " + "Melgarejo"
    mailmap.write_text(f"{token} <old@email.com>\n", encoding="utf-8")

    errors = repo_hygiene.scan_forbidden_identity(tmp_path, [".mailmap"])

    assert errors == []


# ---------------------------------------------------------------------------
# CLAUDE.md — portable-paths rule (§ 6 Git Hygiene, lockstep w/ orama)
# ---------------------------------------------------------------------------

def test_claude_md_is_not_in_personal_path_exceptions():
    """CLAUDE.md must not appear in PERSONAL_PATH_EXCEPTIONS — it stays scanned."""
    repo_hygiene = load_repo_hygiene()
    assert "CLAUDE.md" not in repo_hygiene.PERSONAL_PATH_EXCEPTIONS


def test_claude_md_passes_personal_path_scan():
    """The live CLAUDE.md must contain no real workstation paths."""
    repo_hygiene = load_repo_hygiene()
    claude_md = ROOT / "CLAUDE.md"
    assert claude_md.exists(), "CLAUDE.md not found at repo root"

    errors = repo_hygiene.scan_personal_paths(ROOT, ["CLAUDE.md"])

    assert errors == [], (
        "CLAUDE.md contains a personal/workstation path — "
        "use ~, $REPO_ROOT, or $OPENCLAW_ROOT instead:\n" + "\n".join(errors)
    )


def test_claude_md_with_workstation_path_is_blocked(tmp_path):
    """scan_personal_paths blocks a CLAUDE.md that leaks a real developer path.

    Regression guard: the enforcement must hold even though the documentation
    bullet explaining the rule was removed from CLAUDE.md in this PR.
    """
    repo_hygiene = load_repo_hygiene()
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(
        "## Setup\n"
        "Run `bash /Users/johndoe/projects/perpetua-tools/scripts/setup.sh`\n",
        encoding="utf-8",
    )

    errors = repo_hygiene.scan_personal_paths(tmp_path, ["CLAUDE.md"])

    assert len(errors) == 1
    assert "CLAUDE.md:2" in errors[0]
    assert "/Users/johndoe/" in errors[0]


def test_claude_md_with_home_path_is_blocked(tmp_path):
    """/home/<user>/ paths in CLAUDE.md are blocked (Linux workstation leak)."""
    repo_hygiene = load_repo_hygiene()
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(
        "cd /home/devuser/code/perpetua-tools && npm install\n",
        encoding="utf-8",
    )

    errors = repo_hygiene.scan_personal_paths(tmp_path, ["CLAUDE.md"])

    assert len(errors) == 1
    assert "/home/devuser/" in errors[0]


def test_claude_md_with_portable_paths_passes(tmp_path):
    """CLAUDE.md using portable path tokens must pass the scan cleanly."""
    repo_hygiene = load_repo_hygiene()
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(
        "## Setup\n"
        "Run from `$OPENCLAW_ROOT` or `$REPO_ROOT`.\n"
        "Shorthand: `~/projects/perpetua-tools`.\n"
        "Example path: /Users/you/projects is fine (placeholder username).\n",
        encoding="utf-8",
    )

    errors = repo_hygiene.scan_personal_paths(tmp_path, ["CLAUDE.md"])

    assert errors == [], f"Portable-path CLAUDE.md should pass: {errors}"


# ---------------------------------------------------------------------------
# full script smoke test
# ---------------------------------------------------------------------------

def test_repo_hygiene_script_runs_clean():
    result = subprocess.run(
        [sys.executable, "scripts/review/repo_hygiene.py", "."],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 0, result.stdout + result.stderr
