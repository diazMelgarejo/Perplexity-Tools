"""Tests for new/changed git hygiene shell scripts in this PR.

Covers:
- scripts/git/banned_attribution_lib.sh  (new)
- scripts/git/ensure_hooks_installed.sh  (new)
- scripts/cursor/ci-bootstrap-private-attribution.sh  (new — idempotency, permissions)
- scripts/git/audit_attribution.sh  (GIT_AUDIT_RANGE / GIT_AUDIT_STRICT — new section)
- audit_attribution.sh author_ok() changes  (cursoragent rejected, coderabbitai accepted)
"""
from __future__ import annotations

import os
import subprocess
import stat
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "scripts/git/banned_attribution_lib.sh"
ENSURE_HOOKS = ROOT / "scripts/git/ensure_hooks_installed.sh"
CI_BOOTSTRAP = ROOT / "scripts/cursor/ci-bootstrap-private-attribution.sh"
AUDIT = ROOT / "scripts/git/audit_attribution.sh"
INSTALL_HOOKS = ROOT / "scripts/git/install-local-hooks.sh"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_bash(script: str, *, cwd=None, env=None, check=False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        cwd=cwd or ROOT,
        env=env,
        check=check,
    )


def _source_lib(script: str, *, env=None, cwd=None) -> subprocess.CompletedProcess:
    """Source banned_attribution_lib.sh then run the given bash snippet."""
    full = f'source "{LIB}"\n{script}'
    return _run_bash(full, env=env, cwd=cwd)


def _write_patterns(directory: Path, tokens: list[str]) -> Path:
    """Write a banned-attribution-patterns file under directory/.cursor/private/."""
    private = directory / ".cursor" / "private"
    private.mkdir(parents=True, exist_ok=True)
    patterns = private / "banned-attribution-patterns"
    patterns.write_text(
        "# comment line — ignored\n" + "\n".join(tokens) + "\n",
        encoding="utf-8",
    )
    return patterns


def _make_git_repo(directory: Path) -> None:
    """Initialise a minimal git repo with a commit at *directory*."""
    subprocess.run(["git", "init", str(directory)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "cyre@test.invalid"],
        check=True,
        capture_output=True,
        cwd=str(directory),
    )
    subprocess.run(
        ["git", "config", "user.name", "cyre"],
        check=True,
        capture_output=True,
        cwd=str(directory),
    )
    (directory / "README.md").write_text("test repo\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README.md"],
        check=True,
        capture_output=True,
        cwd=str(directory),
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        check=True,
        capture_output=True,
        cwd=str(directory),
    )


# ---------------------------------------------------------------------------
# banned_attribution_lib.sh — banned_patterns_file()
# ---------------------------------------------------------------------------


class TestBannedPatternsFile:
    """banned_patterns_file() prefers .cursor/private over ~/.cursor/openclaw."""

    def test_returns_private_path_when_private_file_exists(self, tmp_path):
        _write_patterns(tmp_path, ["token-alpha"])
        result = _source_lib(
            f'banned_patterns_file "{tmp_path}"',
        )
        assert result.returncode == 0
        assert str(tmp_path / ".cursor/private/banned-attribution-patterns") in result.stdout

    def test_falls_back_to_openclaw_when_private_missing(self, tmp_path):
        openclaw = tmp_path / ".cursor" / "openclaw"
        openclaw.mkdir(parents=True)
        oc_patterns = openclaw / "banned-attribution-patterns"
        oc_patterns.write_text("fallback-token\n", encoding="utf-8")

        env = {
            **os.environ,
            "HOME": str(tmp_path),
            "OPENCLAW_ATTRIBUTION_PATTERNS": str(oc_patterns),
        }
        result = _source_lib(f'banned_patterns_file "{tmp_path}"', env=env)
        assert result.returncode == 0
        assert str(oc_patterns) in result.stdout

    def test_returns_private_path_even_when_missing_as_default(self, tmp_path):
        """When neither file exists, private path is still returned as the canonical placeholder."""
        result = _source_lib(f'banned_patterns_file "{tmp_path}"')
        assert result.returncode == 0
        # Returns a path (doesn't crash), even if it doesn't exist yet
        expected = str(tmp_path / ".cursor/private/banned-attribution-patterns")
        assert expected in result.stdout

    def test_private_takes_priority_over_openclaw_env(self, tmp_path):
        """Private path wins even when OPENCLAW_ATTRIBUTION_PATTERNS points elsewhere."""
        _write_patterns(tmp_path, ["private-wins"])
        fake_oc = tmp_path / "other" / "banned-attribution-patterns"
        fake_oc.parent.mkdir(parents=True)
        fake_oc.write_text("openclaw-token\n", encoding="utf-8")
        env = {**os.environ, "OPENCLAW_ATTRIBUTION_PATTERNS": str(fake_oc)}
        result = _source_lib(f'banned_patterns_file "{tmp_path}"', env=env)
        assert result.returncode == 0
        assert str(tmp_path / ".cursor/private/banned-attribution-patterns") in result.stdout
        assert str(fake_oc) not in result.stdout


# ---------------------------------------------------------------------------
# banned_attribution_lib.sh — banned_patterns_ready()
# ---------------------------------------------------------------------------


class TestBannedPatternsReady:
    def test_returns_zero_when_file_exists_and_nonempty(self, tmp_path):
        _write_patterns(tmp_path, ["some-token"])
        result = _source_lib(f'banned_patterns_ready "{tmp_path}"')
        assert result.returncode == 0

    def test_returns_nonzero_when_file_missing(self, tmp_path):
        result = _source_lib(f'banned_patterns_ready "{tmp_path}"')
        assert result.returncode != 0

    def test_returns_nonzero_when_file_empty(self, tmp_path):
        private = tmp_path / ".cursor" / "private"
        private.mkdir(parents=True)
        (private / "banned-attribution-patterns").write_text("", encoding="utf-8")
        result = _source_lib(f'banned_patterns_ready "{tmp_path}"')
        assert result.returncode != 0


# ---------------------------------------------------------------------------
# banned_attribution_lib.sh — list_banned_pattern_tokens()
# ---------------------------------------------------------------------------


class TestListBannedPatternTokens:
    def test_lists_plain_tokens(self, tmp_path):
        _write_patterns(tmp_path, ["alpha", "beta"])
        result = _source_lib(
            f'list_banned_pattern_tokens "{tmp_path}"',
        )
        assert result.returncode == 0
        tokens = [t for t in result.stdout.splitlines() if t]
        assert "alpha" in tokens
        assert "beta" in tokens

    def test_strips_comment_lines(self, tmp_path):
        private = tmp_path / ".cursor" / "private"
        private.mkdir(parents=True)
        (private / "banned-attribution-patterns").write_text(
            "# this is a comment\ntokenA\n# another comment\ntokenB\n",
            encoding="utf-8",
        )
        result = _source_lib(f'list_banned_pattern_tokens "{tmp_path}"')
        assert result.returncode == 0
        tokens = result.stdout.splitlines()
        assert "tokenA" in tokens
        assert "tokenB" in tokens
        assert any("comment" in t for t in tokens) is False

    def test_strips_inline_comment_after_token(self, tmp_path):
        private = tmp_path / ".cursor" / "private"
        private.mkdir(parents=True)
        (private / "banned-attribution-patterns").write_text(
            "tokenC # inline comment\n",
            encoding="utf-8",
        )
        result = _source_lib(f'list_banned_pattern_tokens "{tmp_path}"')
        tokens = [t for t in result.stdout.splitlines() if t]
        assert "tokenC" in tokens
        assert not any("#" in t for t in tokens)

    def test_skips_blank_lines(self, tmp_path):
        private = tmp_path / ".cursor" / "private"
        private.mkdir(parents=True)
        (private / "banned-attribution-patterns").write_text(
            "\ntokenD\n\n   \ntokenE\n",
            encoding="utf-8",
        )
        result = _source_lib(f'list_banned_pattern_tokens "{tmp_path}"')
        tokens = [t for t in result.stdout.splitlines() if t]
        assert "tokenD" in tokens
        assert "tokenE" in tokens
        # No blank or whitespace-only entries
        assert all(t.strip() for t in tokens)

    def test_returns_nonzero_when_file_missing(self, tmp_path):
        result = _source_lib(f'list_banned_pattern_tokens "{tmp_path}"')
        assert result.returncode != 0

    def test_strips_leading_trailing_whitespace_from_tokens(self, tmp_path):
        private = tmp_path / ".cursor" / "private"
        private.mkdir(parents=True)
        (private / "banned-attribution-patterns").write_text(
            "  tokenF  \n\ttokenG\t\n",
            encoding="utf-8",
        )
        result = _source_lib(f'list_banned_pattern_tokens "{tmp_path}"')
        tokens = [t for t in result.stdout.splitlines() if t]
        assert "tokenF" in tokens
        assert "tokenG" in tokens


# ---------------------------------------------------------------------------
# banned_attribution_lib.sh — line_matches_banned_pattern()
# ---------------------------------------------------------------------------


class TestLineMatchesBannedPattern:
    def test_matches_exact_token_case_insensitive(self, tmp_path):
        _write_patterns(tmp_path, ["mytoken"])
        result = _source_lib(
            f'line_matches_banned_pattern "co-authored-by: X <MYTOKEN@example.com>" "{tmp_path}"'
        )
        assert result.returncode == 0

    def test_matches_substring(self, tmp_path):
        _write_patterns(tmp_path, ["sub"])
        result = _source_lib(
            f'line_matches_banned_pattern "co-authored-by: Foo <foo-sub-bar@x.com>" "{tmp_path}"'
        )
        assert result.returncode == 0

    def test_no_match_returns_nonzero(self, tmp_path):
        _write_patterns(tmp_path, ["secret"])
        result = _source_lib(
            f'line_matches_banned_pattern "co-authored-by: Legit <legit@example.com>" "{tmp_path}"'
        )
        assert result.returncode != 0

    def test_empty_patterns_file_never_matches(self, tmp_path):
        private = tmp_path / ".cursor" / "private"
        private.mkdir(parents=True)
        (private / "banned-attribution-patterns").write_text("", encoding="utf-8")
        result = _source_lib(
            f'line_matches_banned_pattern "anything-here" "{tmp_path}"'
        )
        # Empty pattern file: no tokens → never matches
        assert result.returncode != 0

    def test_matches_against_multiple_tokens(self, tmp_path):
        _write_patterns(tmp_path, ["alpha", "beta", "gamma"])
        for token in ("alpha", "beta", "gamma"):
            result = _source_lib(
                f'line_matches_banned_pattern "co-authored-by: X <{token}@x.com>" "{tmp_path}"'
            )
            assert result.returncode == 0, f"Expected match for {token}"


# ---------------------------------------------------------------------------
# banned_attribution_lib.sh — first_banned_pattern_token()
# ---------------------------------------------------------------------------


class TestFirstBannedPatternToken:
    def test_returns_first_non_comment_token(self, tmp_path):
        private = tmp_path / ".cursor" / "private"
        private.mkdir(parents=True)
        (private / "banned-attribution-patterns").write_text(
            "# comment\nfirsttoken\nsecondtoken\n",
            encoding="utf-8",
        )
        result = _source_lib(f'first_banned_pattern_token "{tmp_path}"')
        assert result.returncode == 0
        assert result.stdout.strip() == "firsttoken"

    def test_returns_nonzero_when_file_missing(self, tmp_path):
        result = _source_lib(f'first_banned_pattern_token "{tmp_path}"')
        assert result.returncode != 0

    def test_returns_nonzero_when_only_comments(self, tmp_path):
        private = tmp_path / ".cursor" / "private"
        private.mkdir(parents=True)
        (private / "banned-attribution-patterns").write_text(
            "# only comments\n# no real tokens\n",
            encoding="utf-8",
        )
        result = _source_lib(f'first_banned_pattern_token "{tmp_path}"')
        assert result.returncode != 0


# ---------------------------------------------------------------------------
# ensure_hooks_installed.sh
#
# The script derives REPO_ROOT from BASH_SOURCE[0] (its own location inside
# ROOT/scripts/git/), so env-var overrides have no effect. We test the
# *same logic* by inlining the check body with an explicit REPO_ROOT arg,
# mirroring the script verbatim. We also add one smoke test that runs the
# real script against the actual Perpetua-Tools repo.
# ---------------------------------------------------------------------------

# Bash snippet reproducing ensure_hooks_installed.sh check logic, but with
# REPO_ROOT passed as $1 so we can point it at an arbitrary tmp_path repo.
_ENSURE_HOOKS_INLINE = """\
set -euo pipefail
REPO_ROOT="$1"
cd "$REPO_ROOT"
if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "ERROR: not a git repository: $REPO_ROOT" >&2
  exit 1
fi
hooks_path="$(git config --local --get core.hooksPath 2>/dev/null || true)"
if [[ "$hooks_path" != ".githooks" ]]; then
  echo "ERROR: core.hooksPath=${hooks_path:-<unset>} \xe2\x80\x94 expected .githooks" >&2
  echo "Run: bash scripts/git/install-local-hooks.sh" >&2
  exit 1
fi
for hook in pre-commit commit-msg pre-push; do
  path="$REPO_ROOT/.githooks/$hook"
  if [[ ! -f "$path" || ! -x "$path" ]]; then
    echo "ERROR: missing or non-executable $path" >&2
    echo "Run: bash scripts/git/install-local-hooks.sh" >&2
    exit 1
  fi
done
exit 0
"""


def _run_ensure_hooks_logic(repo_root: Path) -> subprocess.CompletedProcess:
    """Run ensure_hooks_installed.sh check logic against *repo_root*."""
    return subprocess.run(
        ["bash", "-c", _ENSURE_HOOKS_INLINE, "--", str(repo_root)],
        capture_output=True,
        text=True,
    )


class TestEnsureHooksInstalled:
    """ensure_hooks_installed.sh checks that core.hooksPath=.githooks and hooks exist/are executable."""

    def _setup_hooks_repo(self, directory: Path) -> None:
        """Create a git repo with .githooks/ hooks all present and executable."""
        _make_git_repo(directory)
        githooks = directory / ".githooks"
        githooks.mkdir()
        for hook in ("pre-commit", "commit-msg", "pre-push"):
            h = githooks / hook
            h.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            h.chmod(0o755)
        subprocess.run(
            ["git", "config", "--local", "core.hooksPath", ".githooks"],
            check=True,
            capture_output=True,
            cwd=str(directory),
        )

    def test_passes_when_hooks_installed_correctly(self, tmp_path):
        self._setup_hooks_repo(tmp_path)
        result = _run_ensure_hooks_logic(tmp_path)
        assert result.returncode == 0

    def test_fails_when_hooksPath_not_set(self, tmp_path):
        _make_git_repo(tmp_path)
        githooks = tmp_path / ".githooks"
        githooks.mkdir()
        for hook in ("pre-commit", "commit-msg", "pre-push"):
            h = githooks / hook
            h.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            h.chmod(0o755)
        # Do NOT set core.hooksPath
        result = _run_ensure_hooks_logic(tmp_path)
        assert result.returncode != 0
        assert ".githooks" in result.stderr

    def test_fails_when_hooksPath_is_wrong_value(self, tmp_path):
        _make_git_repo(tmp_path)
        subprocess.run(
            ["git", "config", "--local", "core.hooksPath", "/some/other/path"],
            check=True,
            capture_output=True,
            cwd=str(tmp_path),
        )
        result = _run_ensure_hooks_logic(tmp_path)
        assert result.returncode != 0
        assert ".githooks" in result.stderr

    def test_fails_when_pre_commit_missing(self, tmp_path):
        self._setup_hooks_repo(tmp_path)
        (tmp_path / ".githooks" / "pre-commit").unlink()
        result = _run_ensure_hooks_logic(tmp_path)
        assert result.returncode != 0
        assert "pre-commit" in result.stderr

    def test_fails_when_commit_msg_not_executable(self, tmp_path):
        self._setup_hooks_repo(tmp_path)
        cm = tmp_path / ".githooks" / "commit-msg"
        cm.chmod(0o644)  # remove execute bit
        result = _run_ensure_hooks_logic(tmp_path)
        assert result.returncode != 0
        assert "commit-msg" in result.stderr

    def test_fails_when_pre_push_missing(self, tmp_path):
        """pre-push is a new hook added in this PR — must be verified by ensure_hooks_installed."""
        self._setup_hooks_repo(tmp_path)
        (tmp_path / ".githooks" / "pre-push").unlink()
        result = _run_ensure_hooks_logic(tmp_path)
        assert result.returncode != 0

    def test_error_message_mentions_install_command(self, tmp_path):
        """Error output must guide the user to the fix command."""
        _make_git_repo(tmp_path)
        result = _run_ensure_hooks_logic(tmp_path)
        assert result.returncode != 0
        combined = result.stdout + result.stderr
        assert "install-local-hooks.sh" in combined

    def test_real_script_passes_on_this_repo(self):
        """The real ensure_hooks_installed.sh must pass on the actual Perpetua-Tools repo."""
        result = subprocess.run(
            ["bash", str(ENSURE_HOOKS)],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        assert result.returncode == 0, (
            f"ensure_hooks_installed.sh failed on the actual repo:\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )


# ---------------------------------------------------------------------------
# ci-bootstrap-private-attribution.sh — idempotency and file properties
# ---------------------------------------------------------------------------


class TestCiBootstrapPrivateAttribution:
    """Verify ci-bootstrap-private-attribution.sh behavior: creation and idempotency."""

    def _run_bootstrap(
        self, home_dir: Path, repo_root: Path | None = None
    ) -> subprocess.CompletedProcess:
        env = {**os.environ, "HOME": str(home_dir)}
        return subprocess.run(
            ["bash", str(CI_BOOTSTRAP)],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(repo_root or ROOT),
        )

    def test_creates_openclaw_patterns_file(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        result = self._run_bootstrap(home)
        assert result.returncode == 0
        patterns = home / ".cursor" / "openclaw" / "banned-attribution-patterns"
        assert patterns.is_file()
        assert patterns.stat().st_size > 0

    def test_creates_private_patterns_file(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        result = self._run_bootstrap(home)
        assert result.returncode == 0
        private = ROOT / ".cursor" / "private" / "banned-attribution-patterns"
        assert private.is_file()
        assert private.stat().st_size > 0

    def test_idempotent_when_both_files_already_present(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        # First run: creates files
        r1 = self._run_bootstrap(home)
        assert r1.returncode == 0
        assert "OK: CI bootstrap" in r1.stdout

        # Second run: must be idempotent (exit 0, "already present" message)
        r2 = self._run_bootstrap(home)
        assert r2.returncode == 0
        assert "already present" in r2.stdout

    def test_openclaw_patterns_file_has_restricted_permissions(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        result = self._run_bootstrap(home)
        assert result.returncode == 0
        patterns = home / ".cursor" / "openclaw" / "banned-attribution-patterns"
        mode = patterns.stat().st_mode
        # Should be 0600: owner read/write only
        assert stat.S_IMODE(mode) == 0o600

    def test_tokens_are_non_empty_strings(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        self._run_bootstrap(home)
        patterns = home / ".cursor" / "openclaw" / "banned-attribution-patterns"
        content = patterns.read_text(encoding="utf-8")
        tokens = [
            line.split("#", 1)[0].strip()
            for line in content.splitlines()
            if line.split("#", 1)[0].strip()
        ]
        assert len(tokens) >= 1, "At least one non-comment token must be present"
        for token in tokens:
            assert len(token) > 2, f"Token too short to be meaningful: {token!r}"

    def test_output_mentions_both_destinations(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        result = self._run_bootstrap(home)
        assert result.returncode == 0
        # First run output should mention the openclaw path
        combined = result.stdout + result.stderr
        assert "OK: CI bootstrap" in combined

    def test_partial_run_creates_both_files_on_retry(self, tmp_path):
        """If only the openclaw file exists (partial previous run), re-running creates the private file."""
        home = tmp_path / "home"
        home.mkdir()
        openclaw = home / ".cursor" / "openclaw"
        openclaw.mkdir(parents=True)
        # Manually create only the openclaw file — simulating partial first run
        (openclaw / "banned-attribution-patterns").write_text("partial-token\n", encoding="utf-8")

        result = self._run_bootstrap(home)
        assert result.returncode == 0
        # Both should now exist
        assert (openclaw / "banned-attribution-patterns").is_file()
        private = ROOT / ".cursor" / "private" / "banned-attribution-patterns"
        assert private.is_file()

    def test_second_run_is_no_op_and_does_not_modify_files(self, tmp_path):
        """Idempotency: the second run must not change the patterns file content."""
        home = tmp_path / "home"
        home.mkdir()
        self._run_bootstrap(home)
        patterns = home / ".cursor" / "openclaw" / "banned-attribution-patterns"
        content_before = patterns.read_bytes()

        self._run_bootstrap(home)  # second run
        content_after = patterns.read_bytes()
        # Content must be unchanged on second run (idempotent)
        assert content_before == content_after


# ---------------------------------------------------------------------------
# audit_attribution.sh — author_ok() changes (cursoragent rejected, coderabbitai accepted)
# ---------------------------------------------------------------------------


class TestAuditAttributionAuthorPolicy:
    """Test author_ok() logic changes by inlining the function in a bash subprocess.

    We inline the exact author_ok() body from audit_attribution.sh rather than
    sourcing the full script (which requires a git repo with history to scan).
    """

    def _author_ok(self, email: str, name: str, tmp_path: Path) -> bool:
        """Run author_ok() inline with the exact logic from audit_attribution.sh."""
        _write_patterns(tmp_path, ["banned-token-xyz"])
        # Reproduce the author_ok() body verbatim from the diff
        script = textwrap.dedent(f"""\
            set -euo pipefail
            source "{LIB}"
            REPO_ROOT="{tmp_path}"
            ALLOWED_HUMAN_AE="diazmelgarejo@gmail.com lawrence@cyre.me codex@openai.com"
            ALLOWED_BOT_ORAMA="cursor[bot]@users.noreply.github.com"
            ALLOWED_BOT_PT="dependabot[bot]@users.noreply.github.com coderabbitai[bot]@users.noreply.github.com"
            ALLOWED_BOT_EMAILS="$ALLOWED_BOT_ORAMA $ALLOWED_BOT_PT"

            author_ok() {{
              local ae_lc="$1"
              local an_lc="$2"
              if [[ "$ae_lc" == "cursoragent@cursor.com" ]] || [[ "$an_lc" == *cursor*agent* ]]; then
                return 1
              fi
              if [[ "$ae_lc" == *"[bot]@users.noreply.github.com" ]]; then
                return 0
              fi
              local bot
              for bot in $ALLOWED_BOT_EMAILS; do
                [[ "$ae_lc" == "$(printf '%s' "$bot" | tr '[:upper:]' '[:lower:]')" ]] && return 0
              done
              local h
              for h in $ALLOWED_HUMAN_AE; do
                [[ "$ae_lc" == "$h" ]] && return 0
              done
              return 1
            }}

            ae_lc="$(printf '%s' '{email}' | tr '[:upper:]' '[:lower:]')"
            an_lc="$(printf '%s' '{name}' | tr '[:upper:]' '[:lower:]')"
            author_ok "$ae_lc" "$an_lc"
        """)
        result = _run_bash(script, cwd=tmp_path)
        return result.returncode == 0

    def test_cursoragent_email_is_rejected(self, tmp_path):
        assert not self._author_ok("cursoragent@cursor.com", "cyre", tmp_path)

    def test_cursor_agent_name_is_rejected(self, tmp_path):
        assert not self._author_ok("someone@example.com", "Cursor Agent", tmp_path)

    def test_cursor_agent_name_partial_is_rejected(self, tmp_path):
        """Any name containing 'cursor agent' should be rejected."""
        assert not self._author_ok("x@example.com", "Anthropic Cursor Agent Bot", tmp_path)

    def test_approved_human_email_diazmelgarejo_is_accepted(self, tmp_path):
        assert self._author_ok("diazmelgarejo@gmail.com", "cyre", tmp_path)

    def test_approved_cyre_me_email_is_accepted(self, tmp_path):
        assert self._author_ok("lawrence@cyre.me", "cyre", tmp_path)

    def test_codex_is_accepted(self, tmp_path):
        assert self._author_ok("codex@openai.com", "Codex", tmp_path)

    def test_coderabbitai_bot_is_accepted(self, tmp_path):
        """coderabbitai[bot] is a new addition to the allowed-bot list in this PR."""
        assert self._author_ok(
            "coderabbitai[bot]@users.noreply.github.com", "coderabbitai[bot]", tmp_path
        )

    def test_dependabot_is_accepted(self, tmp_path):
        assert self._author_ok(
            "dependabot[bot]@users.noreply.github.com", "dependabot[bot]", tmp_path
        )

    def test_cursor_bot_github_is_accepted(self, tmp_path):
        """cursor[bot] (the GitHub app bot, not the agent) is accepted."""
        assert self._author_ok(
            "cursor[bot]@users.noreply.github.com", "cursor[bot]", tmp_path
        )

    def test_any_github_bot_wildcard_is_accepted(self, tmp_path):
        """Any *[bot]@users.noreply.github.com matches the wildcard rule."""
        assert self._author_ok(
            "renovate[bot]@users.noreply.github.com", "renovate[bot]", tmp_path
        )

    def test_unknown_email_is_rejected(self, tmp_path):
        assert not self._author_ok("random@gmail.com", "Random Person", tmp_path)

    def test_cursoragent_email_rejected_regardless_of_name(self, tmp_path):
        """cursoragent@cursor.com is always rejected — even with an approved name."""
        assert not self._author_ok("cursoragent@cursor.com", "cyre", tmp_path)


# ---------------------------------------------------------------------------
# audit_attribution.sh — GIT_AUDIT_RANGE / GIT_AUDIT_STRICT (new section)
# ---------------------------------------------------------------------------


class TestAuditAttributionRangeMode:
    """Test the GIT_AUDIT_RANGE + GIT_AUDIT_STRICT section added to audit_attribution.sh."""

    def _bootstrap_patterns(self, repo_path: Path) -> None:
        """Install banned patterns into .cursor/private of *repo_path*."""
        home = repo_path / "_home"
        home.mkdir(exist_ok=True)
        env = {**os.environ, "HOME": str(home)}
        subprocess.run(
            ["bash", str(CI_BOOTSTRAP)],
            check=True,
            capture_output=True,
            env=env,
            cwd=str(ROOT),
        )
        openclaw_patterns = home / ".cursor" / "openclaw" / "banned-attribution-patterns"
        if openclaw_patterns.is_file():
            private = repo_path / ".cursor" / "private"
            private.mkdir(parents=True, exist_ok=True)
            (private / "banned-attribution-patterns").write_bytes(openclaw_patterns.read_bytes())

    def _make_repo_with_commits(self, directory: Path, commits: list[dict]) -> None:
        """Create a git repo with custom commits.

        Each commit dict: {msg, author_name?, author_email?}.
        """
        _make_git_repo(directory)
        self._bootstrap_patterns(directory)
        for i, c in enumerate(commits):
            f = directory / f"file{i}.txt"
            f.write_text(f"content {i}\n", encoding="utf-8")
            env = {
                **os.environ,
                "GIT_AUTHOR_NAME": c.get("author_name", "cyre"),
                "GIT_AUTHOR_EMAIL": c.get("author_email", "lawrence@cyre.me"),
                "GIT_COMMITTER_NAME": c.get("author_name", "cyre"),
                "GIT_COMMITTER_EMAIL": c.get("author_email", "lawrence@cyre.me"),
            }
            subprocess.run(
                ["git", "add", f.name], check=True, capture_output=True, cwd=str(directory)
            )
            subprocess.run(
                ["git", "commit", "-m", c["msg"]],
                check=True,
                capture_output=True,
                cwd=str(directory),
                env=env,
            )

    def _get_root_and_head(self, directory: Path) -> tuple[str, str]:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(directory), text=True
        ).strip()
        root_commit = subprocess.check_output(
            ["git", "rev-list", "--max-parents=0", "HEAD"], cwd=str(directory), text=True
        ).strip()
        return root_commit, head

    def test_range_output_line_emitted_when_env_set(self, tmp_path):
        """When GIT_AUDIT_RANGE is set, the script emits a RANGE\\t... line."""
        self._make_repo_with_commits(tmp_path, [
            {"msg": "feat: first clean commit", "author_email": "lawrence@cyre.me"},
        ])
        root_commit, head = self._get_root_and_head(tmp_path)

        env = {**os.environ, "GIT_AUDIT_RANGE": f"{root_commit}..{head}"}
        result = subprocess.run(
            ["bash", str(AUDIT)],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=env,
        )
        combined = result.stdout + result.stderr
        assert "RANGE" in combined, f"Expected RANGE line in output:\n{combined}"

    def test_strict_mode_exits_zero_on_clean_range(self, tmp_path):
        """GIT_AUDIT_STRICT=1 exits 0 when the range has no violations."""
        self._make_repo_with_commits(tmp_path, [
            {"msg": "feat: clean commit", "author_email": "lawrence@cyre.me"},
            {"msg": "fix: another clean one", "author_email": "diazmelgarejo@gmail.com"},
        ])
        root_commit, head = self._get_root_and_head(tmp_path)

        env = {
            **os.environ,
            "GIT_AUDIT_RANGE": f"{root_commit}..{head}",
            "GIT_AUDIT_STRICT": "1",
        }
        result = subprocess.run(
            ["bash", str(AUDIT)],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=env,
        )
        assert result.returncode == 0, (
            f"Expected exit 0 for clean range:\nstdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_strict_mode_exits_nonzero_on_bad_author(self, tmp_path):
        """GIT_AUDIT_STRICT=1 exits 1 when cursoragent appears as commit author."""
        self._make_repo_with_commits(tmp_path, [
            {
                "msg": "feat: injected cursor agent commit",
                "author_name": "Cursor Agent",
                "author_email": "cursoragent@cursor.com",
            },
        ])
        root_commit, head = self._get_root_and_head(tmp_path)

        env = {
            **os.environ,
            "GIT_AUDIT_RANGE": f"{root_commit}..{head}",
            "GIT_AUDIT_STRICT": "1",
        }
        result = subprocess.run(
            ["bash", str(AUDIT)],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=env,
        )
        assert result.returncode != 0

    def test_strict_mode_disabled_exits_zero_even_with_violations(self, tmp_path):
        """Without GIT_AUDIT_STRICT=1, the script reports but does NOT fail on range violations."""
        self._make_repo_with_commits(tmp_path, [
            {
                "msg": "feat: cursor agent commit",
                "author_name": "Cursor Agent",
                "author_email": "cursoragent@cursor.com",
            },
        ])
        root_commit, head = self._get_root_and_head(tmp_path)

        env = {
            **os.environ,
            "GIT_AUDIT_RANGE": f"{root_commit}..{head}",
            # GIT_AUDIT_STRICT deliberately not set
        }
        env.pop("GIT_AUDIT_STRICT", None)
        result = subprocess.run(
            ["bash", str(AUDIT)],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=env,
        )
        # Should exit 0 (strict not enabled) but show violations in output
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert "RANGE" in combined

    def test_range_output_shows_clean_yes_when_no_violations(self, tmp_path):
        """RANGE line in output shows clean=yes for a violation-free range."""
        self._make_repo_with_commits(tmp_path, [
            {"msg": "feat: valid commit", "author_email": "lawrence@cyre.me"},
        ])
        root_commit, head = self._get_root_and_head(tmp_path)

        env = {**os.environ, "GIT_AUDIT_RANGE": f"{root_commit}..{head}"}
        result = subprocess.run(
            ["bash", str(AUDIT)],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=env,
        )
        combined = result.stdout + result.stderr
        assert "clean=yes" in combined

    def test_range_output_shows_clean_no_for_bad_author(self, tmp_path):
        """RANGE line shows clean=no when author policy is violated."""
        self._make_repo_with_commits(tmp_path, [
            {
                "msg": "feat: bad actor",
                "author_name": "Cursor Agent",
                "author_email": "cursoragent@cursor.com",
            },
        ])
        root_commit, head = self._get_root_and_head(tmp_path)

        env = {**os.environ, "GIT_AUDIT_RANGE": f"{root_commit}..{head}"}
        result = subprocess.run(
            ["bash", str(AUDIT)],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=env,
        )
        combined = result.stdout + result.stderr
        assert "clean=no" in combined

    def test_no_range_line_when_git_audit_range_not_set(self, tmp_path):
        """When GIT_AUDIT_RANGE is unset, no RANGE line should appear in output."""
        _make_git_repo(tmp_path)
        self._bootstrap_patterns(tmp_path)
        env = {k: v for k, v in os.environ.items() if k != "GIT_AUDIT_RANGE"}
        result = subprocess.run(
            ["bash", str(AUDIT)],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=env,
        )
        # RANGE line should NOT appear when env var is absent
        assert "RANGE\t" not in result.stdout

    def test_strict_range_with_approved_codex_author_passes(self, tmp_path):
        """Codex (approved AI author) passes GIT_AUDIT_STRICT=1."""
        self._make_repo_with_commits(tmp_path, [
            {
                "msg": "feat: codex authored commit",
                "author_name": "Codex",
                "author_email": "codex@openai.com",
            },
        ])
        root_commit, head = self._get_root_and_head(tmp_path)

        env = {
            **os.environ,
            "GIT_AUDIT_RANGE": f"{root_commit}..{head}",
            "GIT_AUDIT_STRICT": "1",
        }
        result = subprocess.run(
            ["bash", str(AUDIT)],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=env,
        )
        assert result.returncode == 0, (
            f"Codex author should pass strict mode:\nstdout={result.stdout}\nstderr={result.stderr}"
        )


# ---------------------------------------------------------------------------
# audit_attribution.sh — renamed verboten → banned in output columns
# ---------------------------------------------------------------------------


class TestAuditAttributionOutputFormat:
    """Verify the renamed output column (verboten → banned) is used consistently."""

    def _bootstrap_patterns(self, path: Path) -> None:
        home = path / "_home"
        home.mkdir(exist_ok=True)
        env = {**os.environ, "HOME": str(home)}
        subprocess.run(
            ["bash", str(CI_BOOTSTRAP)],
            check=True,
            capture_output=True,
            env=env,
            cwd=str(ROOT),
        )
        openclaw_patterns = home / ".cursor" / "openclaw" / "banned-attribution-patterns"
        if openclaw_patterns.is_file():
            private = path / ".cursor" / "private"
            private.mkdir(parents=True, exist_ok=True)
            (private / "banned-attribution-patterns").write_bytes(openclaw_patterns.read_bytes())

    def test_output_uses_banned_column_not_verboten(self, tmp_path):
        """The audit script output must use 'banned=' not 'verboten=' (renamed in PR)."""
        _make_git_repo(tmp_path)
        self._bootstrap_patterns(tmp_path)
        result = subprocess.run(
            ["bash", str(AUDIT)],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert "banned=" in result.stdout, (
            f"Expected 'banned=' column in output:\n{result.stdout}"
        )
        assert "verboten=" not in result.stdout, (
            f"'verboten=' column should not appear (renamed to 'banned='):\n{result.stdout}"
        )

    def test_output_includes_bad_author_and_bad_coauthor_columns(self, tmp_path):
        """Audit output line must include bad_author= and bad_coauthor= columns."""
        _make_git_repo(tmp_path)
        self._bootstrap_patterns(tmp_path)
        result = subprocess.run(
            ["bash", str(AUDIT)],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert "bad_author=" in result.stdout
        assert "bad_coauthor=" in result.stdout
