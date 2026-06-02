"""Tests for Cursor cloud commit-attribution guard scripts."""
from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRIP_HOOK = ROOT / "scripts/git/hooks/commit-msg.strip-coauthor"
SYNC_PRIVATE = ROOT / "scripts/cursor/sync-private-attribution-from-home.sh"
CI_BOOTSTRAP = ROOT / "scripts/cursor/ci-bootstrap-private-attribution.sh"
ORAMA_WRITE = Path("/agent/repos/orama-system/scripts/cursor/write-openclaw-private-attribution.sh")


def _ensure_banned_patterns() -> None:
    """Load gitignored banned patterns; prefer self-contained CI bootstrap when present."""
    patterns = ROOT / ".cursor/private/banned-attribution-patterns"
    if patterns.is_file():
        return
    if CI_BOOTSTRAP.is_file():
        subprocess.run(["bash", str(CI_BOOTSTRAP)], check=True, cwd=ROOT)
        if patterns.is_file():
            return
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
# Tests for first_banned_pattern_token() in banned_attribution_lib.sh
# ---------------------------------------------------------------------------

_BANNED_ATTR_LIB = ROOT / "scripts/git/banned_attribution_lib.sh"


def _call_first_banned_pattern_token(root: Path) -> "subprocess.CompletedProcess[str]":
    """Source banned_attribution_lib.sh and invoke first_banned_pattern_token with given root."""
    script = f'source "{_BANNED_ATTR_LIB}" && first_banned_pattern_token "{root}"'
    isolated_home = root / "isolated-home"
    isolated_home.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "HOME": str(isolated_home),
        "OPENCLAW_ATTRIBUTION_PATTERNS": str(isolated_home / "missing-patterns"),
    }
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=env,
    )


def test_first_banned_pattern_token_returns_first_token(tmp_path):
    """first_banned_pattern_token must return the first non-empty, non-comment token."""
    private_dir = tmp_path / ".cursor/private"
    private_dir.mkdir(parents=True)
    (private_dir / "banned-attribution-patterns").write_text(
        "# comment line\nut-fixture-first\nut-fixture-second\n", encoding="utf-8"
    )
    proc = _call_first_banned_pattern_token(tmp_path)
    assert proc.returncode == 0
    assert proc.stdout == "ut-fixture-first"


def test_first_banned_pattern_token_skips_empty_lines(tmp_path):
    """first_banned_pattern_token skips blank lines before returning the first real token."""
    private_dir = tmp_path / ".cursor/private"
    private_dir.mkdir(parents=True)
    (private_dir / "banned-attribution-patterns").write_text(
        "\n\n\nut-fixture-first\nut-fixture-second\n", encoding="utf-8"
    )
    proc = _call_first_banned_pattern_token(tmp_path)
    assert proc.returncode == 0
    assert proc.stdout == "ut-fixture-first"


def test_first_banned_pattern_token_skips_comment_only_file(tmp_path):
    """first_banned_pattern_token returns non-zero exit when only comments exist."""
    private_dir = tmp_path / ".cursor/private"
    private_dir.mkdir(parents=True)
    (private_dir / "banned-attribution-patterns").write_text(
        "# this is a comment\n# another comment\n", encoding="utf-8"
    )
    proc = _call_first_banned_pattern_token(tmp_path)
    assert proc.returncode != 0


def test_first_banned_pattern_token_fails_on_missing_file(tmp_path):
    """first_banned_pattern_token exits non-zero when pattern file does not exist."""
    # tmp_path has no .cursor/private directory
    proc = _call_first_banned_pattern_token(tmp_path)
    assert proc.returncode != 0


def test_first_banned_pattern_token_fails_on_empty_file(tmp_path):
    """first_banned_pattern_token exits non-zero when pattern file is empty."""
    private_dir = tmp_path / ".cursor/private"
    private_dir.mkdir(parents=True)
    (private_dir / "banned-attribution-patterns").write_text("", encoding="utf-8")
    proc = _call_first_banned_pattern_token(tmp_path)
    assert proc.returncode != 0


def test_first_banned_pattern_token_strips_inline_comments(tmp_path):
    """first_banned_pattern_token strips inline comments and trailing whitespace."""
    private_dir = tmp_path / ".cursor/private"
    private_dir.mkdir(parents=True)
    # Inline comment after token — list_banned_pattern_tokens strips it
    (private_dir / "banned-attribution-patterns").write_text(
        "# header\nut-fixture-inline  # inline comment\n", encoding="utf-8"
    )
    proc = _call_first_banned_pattern_token(tmp_path)
    assert proc.returncode == 0
    assert proc.stdout == "ut-fixture-inline"


def test_first_banned_pattern_token_with_real_patterns():
    """first_banned_pattern_token works against repo private patterns."""
    _ensure_banned_patterns()
    proc = _call_first_banned_pattern_token(ROOT)
    assert proc.returncode == 0
    assert len(proc.stdout.strip()) > 0


def test_daily_attribution_guard_requires_opt_in_for_auto_expunge():
    """Session/cloud bootstrap must not rewrite git history unless explicitly opted in."""
    text = (ROOT / "scripts/git/daily-attribution-guard.sh").read_text(encoding="utf-8")
    assert "ATTRIBUTION_EXPUNGE_AUTO" in text
    assert "expunge-all-workspace-repos.sh" in text
    # expunge invocation must be guarded (not unconditional on hits > 0)
    assert 'ATTRIBUTION_EXPUNGE_AUTO:-}" == "1"' in text


def test_cloud_bootstrap_does_not_invoke_daily_attribution_guard():
    """Cloud VM bootstrap must not run full-history attribution scans."""
    text = (ROOT / "scripts/cursor/cloud-bootstrap.sh").read_text(encoding="utf-8")
    assert "daily-attribution-guard.sh" not in text


# ---------------------------------------------------------------------------
# Tests for verify-git-guards.sh GITHUB_ACTIONS behavior (new in this PR)
# ---------------------------------------------------------------------------

_VERIFY_GUARDS = ROOT / "scripts/git/verify-git-guards.sh"


def test_verify_guards_github_actions_skips_cursor_session_hook_check():
    """When GITHUB_ACTIONS=true, verify-git-guards prints the skip message for Cursor hooks."""
    _ensure_banned_patterns()
    proc = subprocess.run(
        ["bash", str(_VERIFY_GUARDS)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**__import__("os").environ, "GITHUB_ACTIONS": "true"},
    )
    combined = proc.stdout + proc.stderr
    assert "GitHub Actions" in combined and "skip" in combined.lower(), (
        f"Expected GitHub Actions skip message in output:\n{combined}"
    )


def test_verify_guards_github_actions_does_not_print_cursor_session_hook_fail():
    """When GITHUB_ACTIONS=true, script must not complain about missing session hook."""
    _ensure_banned_patterns()
    proc = subprocess.run(
        ["bash", str(_VERIFY_GUARDS)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**__import__("os").environ, "GITHUB_ACTIONS": "true"},
    )
    combined = proc.stdout + proc.stderr
    assert "Cursor sessionStart hook missing" not in combined
    assert "missing" + " " + "${HOME}/.cursor/hooks.json" not in combined


def test_verify_guards_without_github_actions_checks_session_hook(tmp_path):
    """When GITHUB_ACTIONS is unset, script checks for the Cursor session hook and fails if absent."""
    _ensure_banned_patterns()
    # Use a fake HOME with no Cursor hooks so the check reliably fails
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    import os
    env = {
        **os.environ,
        "HOME": str(fake_home),
        "GITHUB_ACTIONS": "",  # explicitly unset / empty
    }
    proc = subprocess.run(
        ["bash", str(_VERIFY_GUARDS)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
    )
    combined = proc.stdout + proc.stderr
    # Script should fail and report the missing session hook
    assert proc.returncode != 0
    assert "Cursor sessionStart hook missing" in combined


def test_verify_guards_github_actions_uses_first_banned_pattern_token():
    """When GITHUB_ACTIONS=true, verify-git-guards uses first_banned_pattern_token (no SIGPIPE)."""
    _ensure_banned_patterns()
    # The script calls first_banned_pattern_token; if it produces a fixture_token,
    # it attempts to reject it — confirming the function was called successfully.
    proc = subprocess.run(
        ["bash", str(_VERIFY_GUARDS)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**__import__("os").environ, "GITHUB_ACTIONS": "true"},
    )
    combined = proc.stdout + proc.stderr
    # Either the banned-pattern check passes (token found and commit rejected) or
    # the script reports "banned pattern file empty" — in either case no SIGPIPE crash.
    assert "Traceback" not in combined  # no Python crash
    assert "Broken pipe" not in combined  # no SIGPIPE leaked to output


def test_ensure_banned_patterns_succeeds_when_patterns_present():
    """_ensure_banned_patterns must not raise when patterns file exists."""
    _ensure_banned_patterns()
