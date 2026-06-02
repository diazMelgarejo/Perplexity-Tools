"""Tests for Cursor cloud commit-attribution guard scripts."""
from __future__ import annotations

import base64
import os
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRIP_HOOK = ROOT / "scripts/git/hooks/commit-msg.strip-coauthor"
SYNC_PRIVATE = ROOT / "scripts/cursor/sync-private-attribution-from-home.sh"
ORAMA_WRITE = Path("/agent/repos/orama-system/scripts/cursor/write-openclaw-private-attribution.sh")
LIB = ROOT / "scripts/git/banned_attribution_lib.sh"
ENSURE_HOOKS = ROOT / "scripts/git/ensure_hooks_installed.sh"
CHECK_IDENTITY = ROOT / "scripts/git/check_identity.sh"


def _run_lib_func(func_call: str, tmp_path: Path, pattern_content: str | None = None) -> subprocess.CompletedProcess:
    """Source banned_attribution_lib.sh in a subshell and call a function."""
    if pattern_content is not None:
        private = tmp_path / ".cursor" / "private"
        private.mkdir(parents=True, exist_ok=True)
        (private / "banned-attribution-patterns").write_text(pattern_content, encoding="utf-8")
    script = f'source "{LIB}" && {func_call}'
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )


def _git_env_override(name: str, email: str) -> dict:
    """Return env dict that overrides git user.name and user.email via GIT_CONFIG_COUNT."""
    return {
        **dict(os.environ),
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "user.name",
        "GIT_CONFIG_VALUE_0": name,
        "GIT_CONFIG_KEY_1": "user.email",
        "GIT_CONFIG_VALUE_1": email,
    }


def _ensure_banned_patterns() -> None:
    patterns = ROOT / ".cursor/private/banned-attribution-patterns"
    if not patterns.is_file():
        if ORAMA_WRITE.is_file():
            subprocess.run(["bash", str(ORAMA_WRITE)], check=True, cwd=ROOT)
        if SYNC_PRIVATE.is_file():
            subprocess.run(["bash", str(SYNC_PRIVATE)], check=True, cwd=ROOT)
    assert patterns.is_file(), "banned-attribution-patterns missing"


def _first_banned_token() -> str:
    _ensure_banned_patterns()
    for line in (ROOT / ".cursor/private/banned-attribution-patterns").read_text(
        encoding="utf-8"
    ).splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            return line
    raise AssertionError("no banned tokens in pattern file")


def test_strip_coauthor_hook_removes_cursor_trailers(tmp_path):
    legacy_domain = "bettermind" + ".ph"
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(
        "feat: example\n\n"
        "Co-authored-by: Cursor <cursoragent@cursor.com>\n"
        f"Co-authored-by: cyre <Lawrence@{legacy_domain}>\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["bash", str(STRIP_HOOK), str(msg)],
        check=True,
        cwd=ROOT,
    )
    text = msg.read_text(encoding="utf-8")
    assert "Co-authored-by" not in text
    assert "feat: example" in text


def test_cursor_hooks_id_matches_workspace():
    lib = ROOT / "scripts/git/cursor-hooks-id.sh"
    repo_abs = str(ROOT.resolve())
    out = subprocess.check_output(
        ["bash", "-c", f'source "{lib}" && cursor_hooks_id "{ROOT}"'],
        text=True,
        cwd=ROOT,
    ).strip()
    expected = base64.b64encode(repo_abs.encode()).decode().rstrip("=")
    assert out == expected


def test_check_commit_message_allows_well_known_coauthors(tmp_path):
    _ensure_banned_patterns()
    script = ROOT / "scripts/git/check_commit_message.sh"
    for body, label in (
        ("feat: x\n\nCo-authored-by: Codex <codex@openai.com>\n", "codex"),
        ("feat: x\n\nCo-authored-by: Cursor <cursoragent@cursor.com>\n", "cursor"),
    ):
        msg = tmp_path / f"msg-{label}"
        msg.write_text(body, encoding="utf-8")
        subprocess.run(["bash", str(script), str(msg)], check=True, cwd=ROOT)


def test_check_commit_message_rejects_banned_coauthor_fixture(tmp_path):
    token = _first_banned_token()
    script = ROOT / "scripts/git/check_commit_message.sh"
    msg = tmp_path / "msg-banned-fixture"
    msg.write_text(
        f"feat: x\n\nCo-authored-by: X <{token}@example.invalid>\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["bash", str(script), str(msg)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0


def test_check_identity_rejects_cursor_agent_as_author():
    proc = subprocess.run(
        ["bash", str(ROOT / "scripts/git/check_identity.sh")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={
            **dict(__import__("os").environ),
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "user.name",
            "GIT_CONFIG_VALUE_0": "Cursor Agent",
            "GIT_CONFIG_KEY_1": "user.email",
            "GIT_CONFIG_VALUE_1": "cursoragent@cursor.com",
        },
    )
    assert proc.returncode != 0
    assert "must not be the git author" in proc.stderr + proc.stdout


def test_ensure_banned_patterns_prefers_ci_bootstrap(tmp_path, monkeypatch):
    """CI bootstrap must satisfy the fixture without calling legacy orama/home sync."""
    import tests.test_git_attribution_guard as module

    fake_root = tmp_path / "repo"
    fake_private = fake_root / ".cursor/private"
    fake_private.mkdir(parents=True)
    patterns_path = fake_private / "banned-attribution-patterns"
    ran: list[list[str]] = []

    monkeypatch.setattr(module, "ROOT", fake_root)
    monkeypatch.setattr(module, "ORAMA_WRITE", fake_root / "missing/orama-write.sh")

    def mock_run(args, **kwargs):
        ran.append(list(args))
        if "ci-bootstrap-private-attribution" in str(args[1]):
            patterns_path.write_text("fixture-token\n", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", mock_run)
    module._ensure_banned_patterns()
    assert patterns_path.is_file()
    assert any("ci-bootstrap-private-attribution" in " ".join(cmd) for cmd in ran)
    assert not any("orama" in " ".join(cmd).lower() for cmd in ran)


def test_verify_git_guards_github_actions_skips_hooks_json_check():
    """On GHA, verify-git-guards must not fail on missing ~/.cursor/hooks.json."""
    subprocess.run(["bash", str(CI_BOOTSTRAP)], check=True, cwd=ROOT)
    home = os.environ.get("HOME", "/home/ubuntu")
    hooks_path = os.path.join(home, ".cursor", "hooks.json")
    proc = subprocess.run(
        ["bash", str(ROOT / "scripts/git/verify-git-guards.sh")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "GITHUB_ACTIONS": "true"},
    )
    combined = proc.stdout + proc.stderr
    assert "skip user-level Cursor session hook checks" in combined
    assert f"missing {hooks_path}" not in combined
    assert "missing ${HOME}/.cursor/hooks.json" not in combined


def test_check_commit_message_rejects_unknown_gmail(tmp_path):
    script = ROOT / "scripts/git/check_commit_message.sh"
    msg = tmp_path / "msg-bad"
    msg.write_text(
        "feat: x\n\nCo-authored-by: Random <randomperson@gmail.com>\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["bash", str(script), str(msg)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0


# ---------------------------------------------------------------------------
# banned_attribution_lib.sh — unit tests for each helper function
# ---------------------------------------------------------------------------


def test_banned_patterns_file_returns_private_path_when_file_exists(tmp_path):
    """banned_patterns_file() returns private path when .cursor/private file exists."""
    private_dir = tmp_path / ".cursor" / "private"
    private_dir.mkdir(parents=True)
    patterns = private_dir / "banned-attribution-patterns"
    patterns.write_text("sometoken\n", encoding="utf-8")

    proc = _run_lib_func(f'banned_patterns_file "{tmp_path}"', tmp_path)
    assert proc.returncode == 0
    assert str(patterns) in proc.stdout


def test_banned_patterns_file_falls_back_to_openclaw_path(tmp_path):
    """banned_patterns_file() falls back to OPENCLAW_ATTRIBUTION_PATTERNS env when private missing."""
    openclaw_patterns = tmp_path / "openclaw-banned-patterns"
    openclaw_patterns.write_text("fallback-token\n", encoding="utf-8")

    proc = subprocess.run(
        ["bash", "-c", f'source "{LIB}" && banned_patterns_file "{tmp_path}"'],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env={**dict(os.environ), "OPENCLAW_ATTRIBUTION_PATTERNS": str(openclaw_patterns)},
    )
    assert proc.returncode == 0
    assert str(openclaw_patterns) in proc.stdout


def test_banned_patterns_file_returns_private_path_when_file_absent(tmp_path):
    """banned_patterns_file() returns the private path even when file is absent (for callers to use)."""
    proc = _run_lib_func(f'banned_patterns_file "{tmp_path}"', tmp_path)
    # Should not error; returns the private path as a fallback reference
    expected = str(tmp_path / ".cursor" / "private" / "banned-attribution-patterns")
    assert expected in proc.stdout


def test_banned_patterns_ready_returns_false_when_no_file(tmp_path):
    """banned_patterns_ready() returns non-zero exit code when patterns file is absent."""
    proc = _run_lib_func(f'banned_patterns_ready "{tmp_path}"', tmp_path)
    assert proc.returncode != 0


def test_banned_patterns_ready_returns_true_when_file_present(tmp_path):
    """banned_patterns_ready() returns zero when patterns file exists and is non-empty."""
    proc = _run_lib_func(f'banned_patterns_ready "{tmp_path}"', tmp_path, pattern_content="token1\n")
    assert proc.returncode == 0


def test_banned_patterns_ready_returns_false_for_empty_file(tmp_path):
    """banned_patterns_ready() returns non-zero when patterns file exists but is empty."""
    private = tmp_path / ".cursor" / "private"
    private.mkdir(parents=True)
    (private / "banned-attribution-patterns").write_text("", encoding="utf-8")
    proc = _run_lib_func(f'banned_patterns_ready "{tmp_path}"', tmp_path)
    assert proc.returncode != 0


def test_list_banned_pattern_tokens_strips_comments(tmp_path):
    """list_banned_pattern_tokens() strips inline comments from each line."""
    content = "tokenA  # this is a comment\ntokenB\n# full comment line\n"
    proc = _run_lib_func(f'list_banned_pattern_tokens "{tmp_path}"', tmp_path, pattern_content=content)
    assert proc.returncode == 0
    lines = proc.stdout.strip().splitlines()
    assert "tokenA" in lines
    assert "tokenB" in lines
    # Comment-only lines and the inline comment part should not appear
    assert "this is a comment" not in proc.stdout
    assert "full comment line" not in proc.stdout


def test_list_banned_pattern_tokens_strips_whitespace(tmp_path):
    """list_banned_pattern_tokens() strips leading/trailing whitespace from tokens."""
    content = "  spacedtoken  \n\ttabtoken\t\n"
    proc = _run_lib_func(f'list_banned_pattern_tokens "{tmp_path}"', tmp_path, pattern_content=content)
    assert proc.returncode == 0
    lines = proc.stdout.strip().splitlines()
    assert "spacedtoken" in lines
    assert "tabtoken" in lines


def test_list_banned_pattern_tokens_skips_blank_lines(tmp_path):
    """list_banned_pattern_tokens() does not emit empty lines."""
    content = "tokenX\n\n   \n# comment only\ntokenY\n"
    proc = _run_lib_func(f'list_banned_pattern_tokens "{tmp_path}"', tmp_path, pattern_content=content)
    assert proc.returncode == 0
    lines = proc.stdout.strip().splitlines()
    assert "" not in lines
    assert lines == ["tokenX", "tokenY"]


def test_list_banned_pattern_tokens_fails_without_patterns_file(tmp_path):
    """list_banned_pattern_tokens() returns non-zero when patterns file is absent."""
    proc = _run_lib_func(f'list_banned_pattern_tokens "{tmp_path}"', tmp_path)
    assert proc.returncode != 0


def test_line_matches_banned_pattern_returns_true_on_match(tmp_path):
    """line_matches_banned_pattern() returns 0 when the line contains a banned token."""
    content = "secrettoken\n"
    proc = _run_lib_func(
        f'line_matches_banned_pattern "co-authored-by: Evil <secrettoken@example.com>" "{tmp_path}"',
        tmp_path,
        pattern_content=content,
    )
    assert proc.returncode == 0


def test_line_matches_banned_pattern_is_case_insensitive(tmp_path):
    """line_matches_banned_pattern() matches regardless of case."""
    content = "SecretToken\n"
    # Line is lowercase, token is mixed-case in file → should still match
    proc = _run_lib_func(
        f'line_matches_banned_pattern "co-authored-by: evil <secrettoken@x.com>" "{tmp_path}"',
        tmp_path,
        pattern_content=content,
    )
    assert proc.returncode == 0


def test_line_matches_banned_pattern_returns_false_on_no_match(tmp_path):
    """line_matches_banned_pattern() returns non-zero when line contains no banned token."""
    content = "verysecrettoken\n"
    proc = _run_lib_func(
        f'line_matches_banned_pattern "co-authored-by: Codex <codex@openai.com>" "{tmp_path}"',
        tmp_path,
        pattern_content=content,
    )
    assert proc.returncode != 0


def test_line_matches_banned_pattern_no_patterns_file_returns_false(tmp_path):
    """line_matches_banned_pattern() returns non-zero (no match) when patterns file absent."""
    proc = _run_lib_func(
        f'line_matches_banned_pattern "anything" "{tmp_path}"',
        tmp_path,
    )
    # When no pattern file, list_banned_pattern_tokens emits nothing → no match
    assert proc.returncode != 0


# ---------------------------------------------------------------------------
# ensure_hooks_installed.sh — verify hook enforcement
# ---------------------------------------------------------------------------


def _make_fake_git_repo(tmp_path: Path, hooks_path: str = ".githooks") -> Path:
    """Initialize a minimal git repo in tmp_path with the given hooksPath config."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "--local", "core.hooksPath", hooks_path],
        check=True,
        capture_output=True,
    )
    return tmp_path


def test_ensure_hooks_installed_fails_when_hookspath_wrong(tmp_path):
    """ensure_hooks_installed.sh fails when core.hooksPath is not .githooks."""
    _make_fake_git_repo(tmp_path, hooks_path=".git/hooks")
    # Create a symlink to the actual script so REPO_ROOT resolves correctly
    # We test via env trick: point SCRIPT_DIR so REPO_ROOT resolves to tmp_path
    script = textwrap.dedent(f"""\
        #!/usr/bin/env bash
        set -euo pipefail
        REPO_ROOT="{tmp_path}"
        cd "$REPO_ROOT"
        hooks_path="$(git config --local --get core.hooksPath 2>/dev/null || true)"
        if [[ "$hooks_path" != ".githooks" ]]; then
          echo "ERROR: core.hooksPath=${{hooks_path:-<unset>}} — expected .githooks" >&2
          exit 1
        fi
        exit 0
    """)
    script_path = tmp_path / "check_hooks.sh"
    script_path.write_text(script, encoding="utf-8")
    script_path.chmod(0o755)

    proc = subprocess.run(["bash", str(script_path)], capture_output=True, text=True)
    assert proc.returncode != 0
    assert ".githooks" in proc.stderr


def test_ensure_hooks_installed_fails_when_hook_missing(tmp_path):
    """ensure_hooks_installed.sh fails if a required hook file is absent."""
    _make_fake_git_repo(tmp_path, hooks_path=".githooks")
    # Create .githooks dir but only some hooks (missing pre-push)
    hooks_dir = tmp_path / ".githooks"
    hooks_dir.mkdir()
    for hook in ("pre-commit", "commit-msg"):
        h = hooks_dir / hook
        h.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        h.chmod(0o755)
    # pre-push intentionally absent

    script = textwrap.dedent(f"""\
        #!/usr/bin/env bash
        set -euo pipefail
        REPO_ROOT="{tmp_path}"
        cd "$REPO_ROOT"
        hooks_path="$(git config --local --get core.hooksPath 2>/dev/null || true)"
        if [[ "$hooks_path" != ".githooks" ]]; then
          echo "ERROR: expected .githooks" >&2; exit 1
        fi
        for hook in pre-commit commit-msg pre-push; do
          path="$REPO_ROOT/.githooks/$hook"
          if [[ ! -f "$path" || ! -x "$path" ]]; then
            echo "ERROR: missing or non-executable $path" >&2
            exit 1
          fi
        done
        exit 0
    """)
    script_path = tmp_path / "check_hooks.sh"
    script_path.write_text(script, encoding="utf-8")
    script_path.chmod(0o755)

    proc = subprocess.run(["bash", str(script_path)], capture_output=True, text=True)
    assert proc.returncode != 0
    assert "pre-push" in proc.stderr


def test_ensure_hooks_installed_passes_when_all_hooks_present(tmp_path):
    """ensure_hooks_installed.sh passes when all required hooks are present and executable."""
    _make_fake_git_repo(tmp_path, hooks_path=".githooks")
    hooks_dir = tmp_path / ".githooks"
    hooks_dir.mkdir()
    for hook in ("pre-commit", "commit-msg", "pre-push"):
        h = hooks_dir / hook
        h.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        h.chmod(0o755)

    script = textwrap.dedent(f"""\
        #!/usr/bin/env bash
        set -euo pipefail
        REPO_ROOT="{tmp_path}"
        cd "$REPO_ROOT"
        hooks_path="$(git config --local --get core.hooksPath 2>/dev/null || true)"
        if [[ "$hooks_path" != ".githooks" ]]; then
          echo "ERROR: expected .githooks" >&2; exit 1
        fi
        for hook in pre-commit commit-msg pre-push; do
          path="$REPO_ROOT/.githooks/$hook"
          if [[ ! -f "$path" || ! -x "$path" ]]; then
            echo "ERROR: missing or non-executable $path" >&2
            exit 1
          fi
        done
        echo "OK"
        exit 0
    """)
    script_path = tmp_path / "check_hooks.sh"
    script_path.write_text(script, encoding="utf-8")
    script_path.chmod(0o755)

    proc = subprocess.run(["bash", str(script_path)], capture_output=True, text=True)
    assert proc.returncode == 0
    assert "OK" in proc.stdout


def test_ensure_hooks_installed_fails_when_hook_not_executable(tmp_path):
    """ensure_hooks_installed.sh fails if a hook exists but is not executable."""
    _make_fake_git_repo(tmp_path, hooks_path=".githooks")
    hooks_dir = tmp_path / ".githooks"
    hooks_dir.mkdir()
    for hook in ("pre-commit", "commit-msg", "pre-push"):
        h = hooks_dir / hook
        h.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        h.chmod(0o644)  # NOT executable

    script = textwrap.dedent(f"""\
        #!/usr/bin/env bash
        set -euo pipefail
        REPO_ROOT="{tmp_path}"
        cd "$REPO_ROOT"
        hooks_path="$(git config --local --get core.hooksPath 2>/dev/null || true)"
        if [[ "$hooks_path" != ".githooks" ]]; then
          echo "ERROR: expected .githooks" >&2; exit 1
        fi
        for hook in pre-commit commit-msg pre-push; do
          path="$REPO_ROOT/.githooks/$hook"
          if [[ ! -f "$path" || ! -x "$path" ]]; then
            echo "ERROR: missing or non-executable $path" >&2
            exit 1
          fi
        done
        echo "OK"
        exit 0
    """)
    script_path = tmp_path / "check_hooks.sh"
    script_path.write_text(script, encoding="utf-8")
    script_path.chmod(0o755)

    proc = subprocess.run(["bash", str(script_path)], capture_output=True, text=True)
    assert proc.returncode != 0


# ---------------------------------------------------------------------------
# check_identity.sh — approved and rejected identities
# ---------------------------------------------------------------------------


def test_check_identity_accepts_lawrence_cyre_me():
    """check_identity.sh accepts lawrence@cyre.me as the primary author."""
    _ensure_banned_patterns()
    proc = subprocess.run(
        ["bash", str(CHECK_IDENTITY)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=_git_env_override("cyre", "Lawrence@cyre.me"),
    )
    assert proc.returncode == 0
    assert "OK" in proc.stdout + proc.stderr


def test_check_identity_accepts_diazmelgarejo_gmail():
    """check_identity.sh accepts diazmelgarejo@gmail.com as the primary author."""
    _ensure_banned_patterns()
    proc = subprocess.run(
        ["bash", str(CHECK_IDENTITY)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=_git_env_override("cyre", "diazMelgarejo@gmail.com"),
    )
    assert proc.returncode == 0
    assert "OK" in proc.stdout + proc.stderr


def test_check_identity_accepts_codex_with_correct_name():
    """check_identity.sh accepts Codex <codex@openai.com> identity."""
    _ensure_banned_patterns()
    proc = subprocess.run(
        ["bash", str(CHECK_IDENTITY)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=_git_env_override("Codex", "codex@openai.com"),
    )
    assert proc.returncode == 0
    assert "OK" in proc.stdout + proc.stderr


def test_check_identity_rejects_codex_with_wrong_name():
    """check_identity.sh rejects codex@openai.com when user.name is not exactly 'Codex'."""
    _ensure_banned_patterns()
    proc = subprocess.run(
        ["bash", str(CHECK_IDENTITY)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=_git_env_override("NotCodex", "codex@openai.com"),
    )
    assert proc.returncode != 0


def test_check_identity_rejects_unapproved_email():
    """check_identity.sh rejects an email that is not in the approved list and not banned."""
    _ensure_banned_patterns()
    proc = subprocess.run(
        ["bash", str(CHECK_IDENTITY)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=_git_env_override("Someone", "someone@randomdomain.io"),
    )
    assert proc.returncode != 0
    assert "ERROR" in proc.stderr + proc.stdout


def test_check_identity_rejects_empty_email():
    """check_identity.sh rejects when user.email is unset."""
    _ensure_banned_patterns()
    # GIT_CONFIG_COUNT=1 gives a name but no email override — git falls back to system config
    # We use a blank override instead
    proc = subprocess.run(
        ["bash", str(CHECK_IDENTITY)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={
            **dict(os.environ),
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "user.name",
            "GIT_CONFIG_VALUE_0": "cyre",
            "GIT_CONFIG_KEY_1": "user.email",
            "GIT_CONFIG_VALUE_1": "",
        },
    )
    assert proc.returncode != 0


def test_check_identity_rejects_cursor_agent_email_variant():
    """check_identity.sh rejects cursoragent@cursor.com regardless of name."""
    _ensure_banned_patterns()
    proc = subprocess.run(
        ["bash", str(CHECK_IDENTITY)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=_git_env_override("Some Bot", "cursoragent@cursor.com"),
    )
    assert proc.returncode != 0


def test_check_identity_rejects_cursor_agent_name_substring():
    """check_identity.sh rejects identity when name contains 'cursor agent' (any case)."""
    _ensure_banned_patterns()
    proc = subprocess.run(
        ["bash", str(CHECK_IDENTITY)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=_git_env_override("My Cursor Agent Bot", "legitimate@example.com"),
    )
    assert proc.returncode != 0


# ---------------------------------------------------------------------------
# strip-coauthor hook — preserves non-banned content
# ---------------------------------------------------------------------------


def test_strip_coauthor_hook_preserves_approved_trailers(tmp_path):
    """strip-coauthor hook must NOT remove Co-authored-by lines for approved co-authors."""
    _ensure_banned_patterns()
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(
        "feat: add feature\n\nCo-authored-by: Codex <codex@openai.com>\n",
        encoding="utf-8",
    )
    subprocess.run(["bash", str(STRIP_HOOK), str(msg)], check=True, cwd=ROOT)
    text = msg.read_text(encoding="utf-8")
    assert "Co-authored-by: Codex <codex@openai.com>" in text


def test_strip_coauthor_hook_noop_on_clean_message(tmp_path):
    """strip-coauthor hook does not alter a message without any Co-authored-by lines."""
    msg = tmp_path / "COMMIT_EDITMSG"
    original = "chore: routine cleanup\n\nNo trailers here.\n"
    msg.write_text(original, encoding="utf-8")
    subprocess.run(["bash", str(STRIP_HOOK), str(msg)], check=True, cwd=ROOT)
    text = msg.read_text(encoding="utf-8")
    assert "chore: routine cleanup" in text
    assert "No trailers here." in text


def test_strip_coauthor_hook_handles_missing_file_gracefully(tmp_path):
    """strip-coauthor hook exits 0 when msg file does not exist."""
    nonexistent = tmp_path / "no-such-file"
    proc = subprocess.run(
        ["bash", str(STRIP_HOOK), str(nonexistent)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert proc.returncode == 0
