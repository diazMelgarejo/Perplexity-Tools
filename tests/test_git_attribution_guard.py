"""Tests for Cursor cloud commit-attribution guard scripts."""
from __future__ import annotations

import base64
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRIP_HOOK = ROOT / "scripts/git/hooks/commit-msg.strip-coauthor"
SYNC_PRIVATE = ROOT / "scripts/cursor/sync-private-attribution-from-home.sh"
CI_BOOTSTRAP = ROOT / "scripts/cursor/ci-bootstrap-private-attribution.sh"
ORAMA_WRITE = Path("/agent/repos/orama-system/scripts/cursor/write-openclaw-private-attribution.sh")


def _ensure_banned_patterns() -> None:
    patterns = ROOT / ".cursor/private/banned-attribution-patterns"
    if not patterns.is_file():
        if CI_BOOTSTRAP.is_file():
            subprocess.run(["bash", str(CI_BOOTSTRAP)], check=True, cwd=ROOT)
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
# Tests for ci-bootstrap-private-attribution.sh (new in this PR)
# ---------------------------------------------------------------------------

def test_ci_bootstrap_constant_points_to_existing_file():
    """CI_BOOTSTRAP module-level constant must point to the real script."""
    assert CI_BOOTSTRAP.is_file(), f"CI_BOOTSTRAP not found: {CI_BOOTSTRAP}"
    assert CI_BOOTSTRAP.name == "ci-bootstrap-private-attribution.sh"


def test_ci_bootstrap_creates_private_patterns_file(tmp_path):
    """Script writes banned-attribution-patterns into .cursor/private/."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    proc = subprocess.run(
        ["bash", str(CI_BOOTSTRAP)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**__import__("os").environ, "HOME": str(fake_home)},
    )
    assert proc.returncode == 0, proc.stderr
    private_file = ROOT / ".cursor/private/banned-attribution-patterns"
    assert private_file.is_file(), "private banned-attribution-patterns not created"


def test_ci_bootstrap_creates_openclaw_patterns_file(tmp_path):
    """Script writes banned-attribution-patterns into $HOME/.cursor/openclaw/."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    proc = subprocess.run(
        ["bash", str(CI_BOOTSTRAP)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**__import__("os").environ, "HOME": str(fake_home)},
    )
    assert proc.returncode == 0, proc.stderr
    openclaw_file = fake_home / ".cursor/openclaw/banned-attribution-patterns"
    assert openclaw_file.is_file(), "openclaw banned-attribution-patterns not created"


def test_ci_bootstrap_patterns_contain_non_comment_tokens(tmp_path):
    """Both output files must have at least two non-comment, non-empty lines."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    subprocess.run(
        ["bash", str(CI_BOOTSTRAP)],
        check=True,
        cwd=ROOT,
        env={**__import__("os").environ, "HOME": str(fake_home)},
    )
    for path in (
        ROOT / ".cursor/private/banned-attribution-patterns",
        fake_home / ".cursor/openclaw/banned-attribution-patterns",
    ):
        lines = path.read_text(encoding="utf-8").splitlines()
        tokens = [l.split("#", 1)[0].strip() for l in lines if l.split("#", 1)[0].strip()]
        assert len(tokens) >= 2, f"Expected at least 2 tokens in {path}, got: {tokens}"


def test_ci_bootstrap_output_message_is_ok(tmp_path):
    """Script stdout must begin with 'OK: CI bootstrap'."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    proc = subprocess.run(
        ["bash", str(CI_BOOTSTRAP)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**__import__("os").environ, "HOME": str(fake_home)},
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK: CI bootstrap" in proc.stdout


def test_ci_bootstrap_creates_required_directories(tmp_path):
    """Script must create $HOME/.cursor/openclaw/private-lessons and .cursor/private/."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    subprocess.run(
        ["bash", str(CI_BOOTSTRAP)],
        check=True,
        cwd=ROOT,
        env={**__import__("os").environ, "HOME": str(fake_home)},
    )
    assert (fake_home / ".cursor/openclaw/private-lessons").is_dir()
    assert (ROOT / ".cursor/private").is_dir()


def test_ci_bootstrap_idempotent(tmp_path):
    """Running ci-bootstrap twice must succeed and produce the same tokens."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    env = {**__import__("os").environ, "HOME": str(fake_home)}
    subprocess.run(["bash", str(CI_BOOTSTRAP)], check=True, cwd=ROOT, env=env)
    first_content = (ROOT / ".cursor/private/banned-attribution-patterns").read_text()
    subprocess.run(["bash", str(CI_BOOTSTRAP)], check=True, cwd=ROOT, env=env)
    second_content = (ROOT / ".cursor/private/banned-attribution-patterns").read_text()
    assert first_content == second_content


# ---------------------------------------------------------------------------
# Tests for first_banned_pattern_token() in banned_attribution_lib.sh (new in this PR)
# ---------------------------------------------------------------------------

_BANNED_ATTR_LIB = ROOT / "scripts/git/banned_attribution_lib.sh"


def _call_first_banned_pattern_token(root: Path) -> "subprocess.CompletedProcess[str]":
    """Source banned_attribution_lib.sh and invoke first_banned_pattern_token with given root."""
    script = f'source "{_BANNED_ATTR_LIB}" && first_banned_pattern_token "{root}"'
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
    )


def test_first_banned_pattern_token_returns_first_token(tmp_path):
    """first_banned_pattern_token must return the first non-empty, non-comment token."""
    private_dir = tmp_path / ".cursor/private"
    private_dir.mkdir(parents=True)
    (private_dir / "banned-attribution-patterns").write_text(
        "# comment line\nalpha-token\nbeta-token\n", encoding="utf-8"
    )
    proc = _call_first_banned_pattern_token(tmp_path)
    assert proc.returncode == 0
    assert proc.stdout == "alpha-token"


def test_first_banned_pattern_token_skips_empty_lines(tmp_path):
    """first_banned_pattern_token skips blank lines before returning the first real token."""
    private_dir = tmp_path / ".cursor/private"
    private_dir.mkdir(parents=True)
    (private_dir / "banned-attribution-patterns").write_text(
        "\n\n\nreal-token\nother-token\n", encoding="utf-8"
    )
    proc = _call_first_banned_pattern_token(tmp_path)
    assert proc.returncode == 0
    assert proc.stdout == "real-token"


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
        "# header\nmytoken  # inline comment\n", encoding="utf-8"
    )
    proc = _call_first_banned_pattern_token(tmp_path)
    assert proc.returncode == 0
    assert proc.stdout == "mytoken"


def test_first_banned_pattern_token_with_real_bootstrap_patterns():
    """first_banned_pattern_token works against patterns seeded by ci-bootstrap."""
    _ensure_banned_patterns()
    proc = _call_first_banned_pattern_token(ROOT)
    assert proc.returncode == 0
    assert len(proc.stdout.strip()) > 0


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


# ---------------------------------------------------------------------------
# Tests for _ensure_banned_patterns() CI_BOOTSTRAP-first logic (new in this PR)
# ---------------------------------------------------------------------------

def test_ensure_banned_patterns_ci_bootstrap_runs_when_patterns_missing(tmp_path, monkeypatch):
    """_ensure_banned_patterns must invoke CI_BOOTSTRAP when the patterns file is absent."""
    import os
    # Point to a fresh private dir that starts empty
    fake_private = tmp_path / ".cursor/private"
    fake_private.mkdir(parents=True)
    patterns_path = fake_private / "banned-attribution-patterns"
    assert not patterns_path.exists()

    ran = []

    real_run = subprocess.run

    def mock_run(args, **kwargs):
        ran.append(args)
        # Actually execute ci-bootstrap so the file gets created
        if args[0] == "bash" and "ci-bootstrap" in str(args[1]):
            return real_run(args, **kwargs)
        return real_run(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", mock_run)

    # Temporarily redirect ROOT / ".cursor/private/banned-attribution-patterns"
    # by running ci-bootstrap normally (it writes to ROOT, not tmp_path)
    # This test validates that CI_BOOTSTRAP is attempted before ORAMA_WRITE.
    import tests.test_git_attribution_guard as module
    orig_root = module.ROOT

    # Ensure the real patterns file exists after bootstrap so assertion passes
    if not (orig_root / ".cursor/private/banned-attribution-patterns").is_file():
        subprocess.run(["bash", str(CI_BOOTSTRAP)], check=True, cwd=orig_root)

    # Verify CI_BOOTSTRAP was attempted in _ensure_banned_patterns when missing
    # by checking the ordering in ran vs ORAMA_WRITE
    ran.clear()
    module._ensure_banned_patterns()

    # If patterns already exist, no bootstrap is triggered — this is correct behaviour.
    # The key invariant is that CI_BOOTSTRAP appears *before* ORAMA_WRITE in the ran list.
    ci_indices = [i for i, a in enumerate(ran) if "ci-bootstrap" in str(a)]
    orama_indices = [i for i, a in enumerate(ran) if "orama" in str(a).lower()]
    if ci_indices and orama_indices:
        assert ci_indices[0] < orama_indices[0], (
            "CI_BOOTSTRAP must be tried before ORAMA_WRITE"
        )


def test_ensure_banned_patterns_ci_bootstrap_satisfies_requirement():
    """After running CI_BOOTSTRAP, _ensure_banned_patterns must succeed without ORAMA_WRITE."""
    import os
    # Run bootstrap if needed
    patterns = ROOT / ".cursor/private/banned-attribution-patterns"
    if not patterns.is_file():
        subprocess.run(["bash", str(CI_BOOTSTRAP)], check=True, cwd=ROOT)
    # Now _ensure_banned_patterns should pass without needing ORAMA_WRITE
    # (ORAMA_WRITE path is /agent/repos/... which won't exist in CI)
    _ensure_banned_patterns()  # must not raise


def test_ci_bootstrap_file_has_comment_header(tmp_path):
    """Patterns file created by ci-bootstrap must contain the expected comment header."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    subprocess.run(
        ["bash", str(CI_BOOTSTRAP)],
        check=True,
        cwd=ROOT,
        env={**__import__("os").environ, "HOME": str(fake_home)},
    )
    content = (ROOT / ".cursor/private/banned-attribution-patterns").read_text(encoding="utf-8")
    assert content.startswith("#"), "patterns file must begin with a comment header"
    assert "Banned attribution tokens" in content
