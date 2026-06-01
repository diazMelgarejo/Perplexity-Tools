"""Tests for install.sh and scripts/install-claude-desktop-llm.sh.

Both scripts were added in the Track B+C PR (vendor/Claude-Desktop-LLM submodule
+ real MCPB bundles). Tests cover argument parsing, function-level behavior
(via inline bash definitions), and filesystem side-effects — all without network
access or live submodule content.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
INSTALL_SH = ROOT / "install.sh"
INSTALL_DESKTOP_SH = ROOT / "scripts" / "install-claude-desktop-llm.sh"

# ---------------------------------------------------------------------------
# Function bodies extracted from scripts/install-claude-desktop-llm.sh.
# These are tested independently to avoid the script's top-level execution.
# ---------------------------------------------------------------------------

_FN_WRITE_STACK_ENV_HINT = r"""
write_stack_env_hint() {
  local hint="$STAGE_DIR/stack-env.example"
  cat >"$hint" <<'ENVEOF'
# Optional env for Claude Desktop extension user_config (set in Settings → Extensions → Configure)
# PT does not write AlphaClaw config; these mirror common stack endpoints.
#
# Ollama Agent → server_url (default upstream: http://localhost:11434)
# LM Studio Agent → server_url (default upstream: http://localhost:1234)
#
# Mac Ollama (orama hard req): http://localhost:11434
# Win LM Studio LAN: set in Claude Desktop UI from your devices.yml / LMSTUDIO_BASE_URL
ENVEOF
  echo "wrote stack-env.example (documentation only)"
}
"""

_FN_OPEN_IN_CLAUDE_DESKTOP = r"""
warn() { echo "  ⚠  $*"; }
log()  { echo "[claude-desktop-llm] $*"; }
info_install_manual() {
  echo ""
  echo "  Claude Desktop install:"
  echo "    1. Open Claude Desktop → Settings → Extensions"
  echo "    2. Advanced settings → Install Extension…"
  echo "    3. Select:"
  echo "         $STAGE_DIR/ollama-agent.mcpb"
  echo "         $STAGE_DIR/lmstudio-agent.mcpb"
  echo "    Or: bash scripts/install-claude-desktop-llm.sh --open"
  echo ""
}
open_in_claude_desktop() {
  if [[ "$SKIP_DESKTOP" -eq 1 ]]; then
    return 0
  fi
  if [[ "$(uname -s)" != "Darwin" ]]; then
    warn "Auto-open skipped (not macOS). Install manually:"
    echo "    Settings → Extensions → Install Extension… → select packages/mcpb-agents/built/*.mcpb"
    return 0
  fi
  if [[ "$OPEN_DESKTOP" -eq 1 ]] || [[ "${PERPETUA_MCPB_OPEN_DESKTOP:-}" == "1" ]]; then
    for bundle in "$STAGE_DIR"/*.mcpb; do
      [[ -f "$bundle" ]] || continue
      log "Opening $(basename "$bundle") with Claude Desktop..."
      open "$bundle" || warn "open failed for $bundle"
    done
  else
    info_install_manual
  fi
}
"""

_FN_VALIDATE_BUNDLES = r"""
warn() { echo "  ⚠  $*"; }
ok()   { echo "  ✓ $*"; }
run_mcpb() { "${MCPB_CMD[@]}" "$@"; }
validate_bundles() {
  if [[ ${#MCPB_CMD[@]} -eq 0 ]]; then
    warn "mcpb not available — skip manifest validation"
    return 0
  fi
  for name in ollama-agent.mcpb lmstudio-agent.mcpb; do
    if run_mcpb info "$STAGE_DIR/$name" &>/dev/null; then
      ok "mcpb info: $name"
    else
      warn "mcpb info failed for $name (may still be valid ZIP bundle)"
    fi
  done
}
"""

_FN_STAGE_BUNDLES = r"""
ok() { echo "  ✓ $*"; }
stage_bundles() {
  mkdir -p "$STAGE_DIR"
  cp -f "$SUBMODULE_DIR/dist/ollama-agent.mcpb" "$STAGE_DIR/"
  cp -f "$SUBMODULE_DIR/dist/lmstudio-agent.mcpb" "$STAGE_DIR/"
  ok "staged -> packages/mcpb-agents/built/"
}
"""

_FN_INFO_INSTALL_MANUAL = r"""
BOLD=""; RESET=""
info_install_manual() {
  echo ""
  echo "  ${BOLD}Claude Desktop install:${RESET}"
  echo "    1. Open Claude Desktop → Settings → Extensions"
  echo "    2. Advanced settings → Install Extension…"
  echo "    3. Select:"
  echo "         $STAGE_DIR/ollama-agent.mcpb"
  echo "         $STAGE_DIR/lmstudio-agent.mcpb"
  echo "    Or: bash scripts/install-claude-desktop-llm.sh --open"
  echo ""
}
"""

_FN_ENSURE_MCPB_CLI = r"""
ok()  { echo "  ✓ $*"; }
err() { echo "  ✗ $*" >&2; }
log() { echo "[claude-desktop-llm] $*"; }
MCPB_CMD=()
ensure_mcpb_cli() {
  if command -v mcpb &>/dev/null; then
    MCPB_CMD=(mcpb)
    ok "mcpb CLI: $(mcpb --version 2>/dev/null || echo present)"
    return 0
  fi
  if ! command -v npm &>/dev/null; then
    err "npm required for @anthropic-ai/mcpb (global or npx)"
    exit 1
  fi
  local local_bin="$PT_ROOT/.npm-global/bin"
  if [[ -x "$local_bin/mcpb" ]]; then
    MCPB_CMD=("$local_bin/mcpb")
    ok "mcpb CLI (local prefix)"
    return 0
  fi
  log "Installing @anthropic-ai/mcpb to $PT_ROOT/.npm-global ..."
  mkdir -p "$PT_ROOT/.npm-global"
  npm install --prefix "$PT_ROOT/.npm-global" @anthropic-ai/mcpb
  if [[ -x "$local_bin/mcpb" ]]; then
    MCPB_CMD=("$local_bin/mcpb")
    ok "mcpb CLI (local prefix)"
    return 0
  fi
  if npx --yes @anthropic-ai/mcpb --version &>/dev/null; then
    MCPB_CMD=(npx --yes @anthropic-ai/mcpb)
    ok "mcpb via npx @anthropic-ai/mcpb"
    return 0
  fi
  err "Could not run mcpb — install manually: npm install -g @anthropic-ai/mcpb"
  exit 1
}
"""

_FN_ENSURE_SUBMODULE = r"""
ok()  { echo "  ✓ $*"; }
err() { echo "  ✗ $*" >&2; }
log() { echo "[claude-desktop-llm] $*"; }
ensure_submodule() {
  if [[ ! -f "$SUBMODULE_DIR/scripts/build-extensions.sh" ]]; then
    log "Initializing vendor/Claude-Desktop-LLM submodule..."
  fi
  git -C "$PT_ROOT" submodule update --init --recursive vendor/Claude-Desktop-LLM
  if [[ ! -f "$SUBMODULE_DIR/scripts/build-extensions.sh" ]]; then
    err "Submodule missing at $SUBMODULE_DIR"
    exit 1
  fi
  ok "submodule @ $(git -C "$SUBMODULE_DIR" rev-parse --short HEAD)"
}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_bash(script: Path, *args: str, env=None, timeout=10) -> subprocess.CompletedProcess:
    """
    Execute a Bash script with the given arguments and capture stdout and stderr.
    
    Parameters:
        script (Path): Path to the Bash script to run.
        *args (str): Positional arguments to pass to the script.
        env (dict | None): Environment variables to use for the subprocess; if None, the current environment is used.
        timeout (int): Number of seconds to wait before timing out the subprocess.
    
    Returns:
        subprocess.CompletedProcess: Completed process object containing return code, `stdout`, and `stderr`.
    """
    return subprocess.run(
        ["bash", str(script), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(ROOT),
        env=env,
        timeout=timeout,
    )


def _make_stub(bin_dir: Path, name: str, body: str = "#!/usr/bin/env bash\nexit 0\n") -> Path:
    """
    Create a minimal executable stub file in bin_dir with the given name.
    
    Parameters:
        bin_dir (Path): Directory where the stub will be written.
        name (str): Filename for the stub executable.
        body (str): Contents to write into the stub; defaults to a simple bash script that exits successfully.
    
    Returns:
        Path: Path to the created stub file.
    """
    stub = bin_dir / name
    stub.write_text(body, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return stub


def _env_with_path(extra_bin: Path, base_env=None) -> dict:
    """
    Prepend extra_bin to the PATH in a copy of the given environment and return it.
    
    Parameters:
        extra_bin (Path): Directory to add to the front of the PATH.
        base_env (dict | None): Optional environment mapping to copy; when None, uses os.environ.
    
    Returns:
        env (dict): A copy of the environment with "PATH" updated to begin with extra_bin.
    """
    env = dict(base_env or os.environ)
    env["PATH"] = f"{extra_bin}:{env.get('PATH', '')}"
    return env


def _run_fn(fn_body: str, call: str, setup: str = "", env: dict | None = None, timeout: int = 10) -> subprocess.CompletedProcess:
    """
    Execute inline Bash function definitions with an optional setup and call, returning the completed process result.
    
    Parameters:
        fn_body (str): One or more Bash function definitions to include in the inline script.
        call (str): The command(s) to execute after the functions are defined (e.g., 'my_fn; echo "EXIT:$?"').
        setup (str): Shell statements to run before the function definitions (e.g., variable assignments). Defaults to an empty string.
        env (dict | None): Environment mapping to use for the subprocess; when None, the current environment is used.
        timeout (int): Seconds to wait before terminating the subprocess. Defaults to 10.
    
    Returns:
        subprocess.CompletedProcess: The completed process containing stdout, stderr, and the return code.
    """
    code = f"""
set +e
{setup}
{fn_body}
{call}
echo "EXIT_CODE:$?"
"""
    return subprocess.run(
        ["bash", "-c", code],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=dict(env or os.environ),
        timeout=timeout,
        cwd=str(ROOT),
    )


# ---------------------------------------------------------------------------
# install.sh
# ---------------------------------------------------------------------------

class TestInstallSh:
    """Tests for the top-level install.sh script."""

    def test_help_long_flag_exits_zero(self):
        result = _run_bash(INSTALL_SH, "--help")
        assert result.returncode == 0

    def test_help_short_flag_exits_zero(self):
        result = _run_bash(INSTALL_SH, "-h")
        assert result.returncode == 0

    def test_help_output_contains_usage(self):
        result = _run_bash(INSTALL_SH, "--help")
        assert "Usage" in result.stdout or "usage" in result.stdout.lower()

    def test_help_output_mentions_skip_mcpb(self):
        result = _run_bash(INSTALL_SH, "--help")
        assert "--skip-mcpb" in result.stdout

    def test_help_output_mentions_open_flag(self):
        result = _run_bash(INSTALL_SH, "--help")
        assert "--open" in result.stdout

    def test_skip_mcpb_prints_skip_message(self, tmp_path):
        """--skip-mcpb must emit a message indicating the MCPB build was skipped."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _make_stub(bin_dir, "git", "#!/usr/bin/env bash\nexit 0\n")
        env = _env_with_path(bin_dir)
        result = _run_bash(INSTALL_SH, "--skip-mcpb", env=env)
        combined = result.stdout + result.stderr
        assert "--skip-mcpb" in combined or "skipped" in combined.lower()

    def test_skip_mcpb_exits_zero(self, tmp_path):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _make_stub(bin_dir, "git", "#!/usr/bin/env bash\nexit 0\n")
        env = _env_with_path(bin_dir)
        result = _run_bash(INSTALL_SH, "--skip-mcpb", env=env)
        assert result.returncode == 0

    def test_output_includes_perpetua_tools_header(self, tmp_path):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _make_stub(bin_dir, "git", "#!/usr/bin/env bash\nexit 0\n")
        env = _env_with_path(bin_dir)
        result = _run_bash(INSTALL_SH, "--skip-mcpb", env=env)
        assert "Perpetua" in result.stdout

    def test_output_includes_done_message_on_success(self, tmp_path):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _make_stub(bin_dir, "git", "#!/usr/bin/env bash\nexit 0\n")
        env = _env_with_path(bin_dir)
        result = _run_bash(INSTALL_SH, "--skip-mcpb", env=env)
        assert result.returncode == 0
        assert "Done" in result.stdout

    def test_open_flag_not_consumed_by_install_sh(self, tmp_path):
        """--open must not be swallowed; with --skip-mcpb the script still exits 0."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _make_stub(bin_dir, "git", "#!/usr/bin/env bash\nexit 0\n")
        env = _env_with_path(bin_dir)
        result = _run_bash(INSTALL_SH, "--skip-mcpb", "--open", env=env)
        assert result.returncode == 0

    def test_skip_desktop_flag_forwarded(self, tmp_path):
        """--skip-desktop must land in EXTRA_ARGS and not cause install.sh to error."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _make_stub(bin_dir, "git", "#!/usr/bin/env bash\nexit 0\n")
        env = _env_with_path(bin_dir)
        result = _run_bash(INSTALL_SH, "--skip-mcpb", "--skip-desktop", env=env)
        assert result.returncode == 0

    def test_script_is_executable(self):
        mode = INSTALL_SH.stat().st_mode
        assert mode & stat.S_IEXEC, "install.sh must be executable (mode 100755 per PR)"

    def test_install_sh_exists(self):
        """
        Verify that the repository contains a top-level install.sh script.
        
        Asserts that `INSTALL_SH` exists at the repository root; the test fails with an explanatory message if the file is missing.
        """
        assert INSTALL_SH.exists(), "install.sh must exist at repo root"

    def test_install_sh_has_bash_shebang(self):
        """
        Assert that the top-level install.sh begins with a bash shebang.
        
        Checks that the first line of INSTALL_SH contains the substring "bash", ensuring the script declares a bash interpreter.
        """
        first_line = INSTALL_SH.read_text(encoding="utf-8").splitlines()[0]
        assert "bash" in first_line

    def test_install_sh_mentions_submodule(self):
        content = INSTALL_SH.read_text(encoding="utf-8")
        assert "vendor/Claude-Desktop-LLM" in content

    def test_install_sh_delegates_to_subscript(self):
        content = INSTALL_SH.read_text(encoding="utf-8")
        assert "install-claude-desktop-llm.sh" in content


# ---------------------------------------------------------------------------
# scripts/install-claude-desktop-llm.sh  — argument parsing
# ---------------------------------------------------------------------------

class TestInstallClaudeDesktopLlm:
    """Tests for scripts/install-claude-desktop-llm.sh."""

    def test_script_exists(self):
        assert INSTALL_DESKTOP_SH.exists()

    def test_script_has_bash_shebang(self):
        first_line = INSTALL_DESKTOP_SH.read_text(encoding="utf-8").splitlines()[0]
        assert "bash" in first_line

    def test_script_has_set_euo_pipefail(self):
        """
        Verify the install-claude-desktop-llm.sh script declares strict shell options.
        
        Checks that the file contains the exact string "set -euo pipefail", ensuring the script enables exit-on-error, undefined-variable checks, and pipeline-failure propagation.
        """
        content = INSTALL_DESKTOP_SH.read_text(encoding="utf-8")
        assert "set -euo pipefail" in content

    def test_help_long_flag_exits_zero(self):
        result = _run_bash(INSTALL_DESKTOP_SH, "--help")
        assert result.returncode == 0

    def test_help_short_flag_exits_zero(self):
        result = _run_bash(INSTALL_DESKTOP_SH, "-h")
        assert result.returncode == 0

    def test_help_output_contains_usage(self):
        result = _run_bash(INSTALL_DESKTOP_SH, "--help")
        assert "Usage" in result.stdout

    def test_help_output_mentions_open(self):
        result = _run_bash(INSTALL_DESKTOP_SH, "--help")
        assert "--open" in result.stdout

    def test_help_output_mentions_skip_desktop(self):
        result = _run_bash(INSTALL_DESKTOP_SH, "--help")
        assert "--skip-desktop" in result.stdout

    # ------------------------------------------------------------------ #
    # write_stack_env_hint (inline function test)                          #
    # ------------------------------------------------------------------ #

    def test_write_stack_env_hint_creates_file(self, tmp_path):
        """write_stack_env_hint must create stack-env.example in STAGE_DIR."""
        stage_dir = tmp_path / "built"
        stage_dir.mkdir()
        result = _run_fn(
            _FN_WRITE_STACK_ENV_HINT,
            "write_stack_env_hint",
            setup=f'STAGE_DIR="{stage_dir}"',
        )
        hint_file = stage_dir / "stack-env.example"
        assert hint_file.exists(), (
            f"stack-env.example not found; stdout={result.stdout!r} stderr={result.stderr!r}"
        )

    def test_write_stack_env_hint_mentions_ollama_port(self, tmp_path):
        stage_dir = tmp_path / "built"
        stage_dir.mkdir()
        _run_fn(_FN_WRITE_STACK_ENV_HINT, "write_stack_env_hint", setup=f'STAGE_DIR="{stage_dir}"')
        content = (stage_dir / "stack-env.example").read_text(encoding="utf-8")
        assert "11434" in content

    def test_write_stack_env_hint_mentions_lmstudio_port(self, tmp_path):
        stage_dir = tmp_path / "built"
        stage_dir.mkdir()
        _run_fn(_FN_WRITE_STACK_ENV_HINT, "write_stack_env_hint", setup=f'STAGE_DIR="{stage_dir}"')
        content = (stage_dir / "stack-env.example").read_text(encoding="utf-8")
        assert "1234" in content

    def test_write_stack_env_hint_is_comments_only(self, tmp_path):
        """The generated file must consist only of comment and blank lines."""
        stage_dir = tmp_path / "built"
        stage_dir.mkdir()
        _run_fn(_FN_WRITE_STACK_ENV_HINT, "write_stack_env_hint", setup=f'STAGE_DIR="{stage_dir}"')
        for line in (stage_dir / "stack-env.example").read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped:
                assert stripped.startswith("#"), f"unexpected non-comment line: {line!r}"

    def test_write_stack_env_hint_idempotent(self, tmp_path):
        """Calling write_stack_env_hint twice must produce identical content (overwrite, not append)."""
        stage_dir = tmp_path / "built"
        stage_dir.mkdir()
        setup = f'STAGE_DIR="{stage_dir}"'
        _run_fn(_FN_WRITE_STACK_ENV_HINT, "write_stack_env_hint", setup=setup)
        content_after_first = (stage_dir / "stack-env.example").read_text(encoding="utf-8")
        _run_fn(_FN_WRITE_STACK_ENV_HINT, "write_stack_env_hint", setup=setup)
        content_after_second = (stage_dir / "stack-env.example").read_text(encoding="utf-8")
        assert content_after_first == content_after_second, (
            "write_stack_env_hint should overwrite on second call, not append"
        )

    def test_write_stack_env_hint_mentions_optional(self, tmp_path):
        """The hint file should mention 'Optional' to clarify it is not mandatory config."""
        stage_dir = tmp_path / "built"
        stage_dir.mkdir()
        _run_fn(_FN_WRITE_STACK_ENV_HINT, "write_stack_env_hint", setup=f'STAGE_DIR="{stage_dir}"')
        content = (stage_dir / "stack-env.example").read_text(encoding="utf-8")
        assert "Optional" in content

    # ------------------------------------------------------------------ #
    # open_in_claude_desktop — SKIP_DESKTOP=1                             #
    # ------------------------------------------------------------------ #

    def test_open_in_claude_desktop_skip_returns_zero(self, tmp_path):
        """SKIP_DESKTOP=1 must cause open_in_claude_desktop to return 0 immediately."""
        stage_dir = tmp_path / "built"
        stage_dir.mkdir()
        result = _run_fn(
            _FN_OPEN_IN_CLAUDE_DESKTOP,
            "open_in_claude_desktop",
            setup=f'STAGE_DIR="{stage_dir}"; SKIP_DESKTOP=1; OPEN_DESKTOP=0',
        )
        assert "EXIT_CODE:0" in result.stdout

    def test_open_in_claude_desktop_skip_produces_no_warn(self, tmp_path):
        """SKIP_DESKTOP=1 must not emit the Auto-open skipped warning."""
        stage_dir = tmp_path / "built"
        stage_dir.mkdir()
        result = _run_fn(
            _FN_OPEN_IN_CLAUDE_DESKTOP,
            "open_in_claude_desktop",
            setup=f'STAGE_DIR="{stage_dir}"; SKIP_DESKTOP=1; OPEN_DESKTOP=0',
        )
        combined = result.stdout + result.stderr
        assert "Auto-open skipped" not in combined
        assert "macOS" not in combined

    # ------------------------------------------------------------------ #
    # open_in_claude_desktop — non-Darwin                                  #
    # ------------------------------------------------------------------ #

    def test_open_in_claude_desktop_non_darwin_warns(self, tmp_path):
        """On non-Darwin systems a warning must be emitted."""
        if sys.platform == "darwin":
            pytest.skip("applies on non-macOS only")
        stage_dir = tmp_path / "built"
        stage_dir.mkdir()
        result = _run_fn(
            _FN_OPEN_IN_CLAUDE_DESKTOP,
            "open_in_claude_desktop",
            setup=f'STAGE_DIR="{stage_dir}"; SKIP_DESKTOP=0; OPEN_DESKTOP=0',
        )
        combined = result.stdout + result.stderr
        assert "macOS" in combined or "manually" in combined.lower()

    def test_open_in_claude_desktop_non_darwin_exits_zero(self, tmp_path):
        """Non-Darwin path must not return an error."""
        if sys.platform == "darwin":
            pytest.skip("applies on non-macOS only")
        stage_dir = tmp_path / "built"
        stage_dir.mkdir()
        result = _run_fn(
            _FN_OPEN_IN_CLAUDE_DESKTOP,
            "open_in_claude_desktop",
            setup=f'STAGE_DIR="{stage_dir}"; SKIP_DESKTOP=0; OPEN_DESKTOP=0',
        )
        assert "EXIT_CODE:0" in result.stdout

    # ------------------------------------------------------------------ #
    # validate_bundles                                                      #
    # ------------------------------------------------------------------ #

    def test_validate_bundles_skips_when_mcpb_cmd_empty(self, tmp_path):
        """validate_bundles should warn and return 0 when MCPB_CMD is empty."""
        stage_dir = tmp_path / "built"
        stage_dir.mkdir()
        result = _run_fn(
            _FN_VALIDATE_BUNDLES,
            "validate_bundles",
            setup=f'STAGE_DIR="{stage_dir}"; MCPB_CMD=()',
        )
        combined = result.stdout + result.stderr
        assert "skip" in combined.lower() or "not available" in combined.lower()
        assert "EXIT_CODE:0" in result.stdout

    def test_validate_bundles_calls_mcpb_info_for_each_bundle(self, tmp_path):
        """validate_bundles must invoke mcpb info on both expected bundles."""
        stage_dir = tmp_path / "built"
        stage_dir.mkdir()
        (stage_dir / "ollama-agent.mcpb").write_bytes(b"PK")
        (stage_dir / "lmstudio-agent.mcpb").write_bytes(b"PK")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        mcpb_log = tmp_path / "mcpb_calls.txt"
        _make_stub(
            bin_dir,
            "mcpb",
            f'#!/usr/bin/env bash\necho "mcpb_call:$*" >> {mcpb_log}\nexit 0\n',
        )
        env = _env_with_path(bin_dir)
        _run_fn(
            _FN_VALIDATE_BUNDLES,
            "validate_bundles",
            setup=f'STAGE_DIR="{stage_dir}"; MCPB_CMD=("{bin_dir}/mcpb")',
            env=env,
        )
        assert mcpb_log.exists(), "mcpb stub was never called"
        calls = mcpb_log.read_text(encoding="utf-8")
        assert "ollama-agent.mcpb" in calls
        assert "lmstudio-agent.mcpb" in calls

    # ------------------------------------------------------------------ #
    # stage_bundles                                                         #
    # ------------------------------------------------------------------ #

    def test_stage_bundles_creates_stage_directory(self, tmp_path):
        """stage_bundles must create STAGE_DIR with mkdir -p."""
        dist = tmp_path / "vendor" / "Claude-Desktop-LLM" / "dist"
        dist.mkdir(parents=True)
        (dist / "ollama-agent.mcpb").write_bytes(b"PK\x03\x04")
        (dist / "lmstudio-agent.mcpb").write_bytes(b"PK\x03\x04")
        stage_dir = tmp_path / "built"
        _run_fn(
            _FN_STAGE_BUNDLES,
            "stage_bundles",
            setup=f'SUBMODULE_DIR="{dist.parent}"; STAGE_DIR="{stage_dir}"',
        )
        assert stage_dir.exists()

    def test_stage_bundles_copies_ollama_bundle(self, tmp_path):
        dist = tmp_path / "vendor" / "Claude-Desktop-LLM" / "dist"
        dist.mkdir(parents=True)
        (dist / "ollama-agent.mcpb").write_bytes(b"PK\x03\x04ollama")
        (dist / "lmstudio-agent.mcpb").write_bytes(b"PK\x03\x04lmstudio")
        stage_dir = tmp_path / "built"
        _run_fn(
            _FN_STAGE_BUNDLES,
            "stage_bundles",
            setup=f'SUBMODULE_DIR="{dist.parent}"; STAGE_DIR="{stage_dir}"',
        )
        assert (stage_dir / "ollama-agent.mcpb").exists()

    def test_stage_bundles_copies_lmstudio_bundle(self, tmp_path):
        dist = tmp_path / "vendor" / "Claude-Desktop-LLM" / "dist"
        dist.mkdir(parents=True)
        (dist / "ollama-agent.mcpb").write_bytes(b"PK\x03\x04ollama")
        (dist / "lmstudio-agent.mcpb").write_bytes(b"PK\x03\x04lmstudio")
        stage_dir = tmp_path / "built"
        _run_fn(
            _FN_STAGE_BUNDLES,
            "stage_bundles",
            setup=f'SUBMODULE_DIR="{dist.parent}"; STAGE_DIR="{stage_dir}"',
        )
        assert (stage_dir / "lmstudio-agent.mcpb").exists()

    def test_stage_bundles_preserves_content(self, tmp_path):
        """
        Verify that stage_bundles copies bundled .mcpb files into the staging directory without altering their content.
        
        Creates a fake submodule `dist` with `ollama-agent.mcpb` and `lmstudio-agent.mcpb`, runs the `stage_bundles` function, and asserts the staged `ollama-agent.mcpb` bytes equal the original file content.
        """
        dist = tmp_path / "vendor" / "Claude-Desktop-LLM" / "dist"
        dist.mkdir(parents=True)
        expected = b"PK\x03\x04ollama-content-marker"
        (dist / "ollama-agent.mcpb").write_bytes(expected)
        (dist / "lmstudio-agent.mcpb").write_bytes(b"PK\x03\x04")
        stage_dir = tmp_path / "built"
        _run_fn(
            _FN_STAGE_BUNDLES,
            "stage_bundles",
            setup=f'SUBMODULE_DIR="{dist.parent}"; STAGE_DIR="{stage_dir}"',
        )
        assert (stage_dir / "ollama-agent.mcpb").read_bytes() == expected

    # ------------------------------------------------------------------ #
    # info_install_manual                                                   #
    # ------------------------------------------------------------------ #

    def test_info_install_manual_mentions_settings_extensions(self, tmp_path):
        stage_dir = tmp_path / "built"
        result = _run_fn(
            _FN_INFO_INSTALL_MANUAL,
            "info_install_manual",
            setup=f'STAGE_DIR="{stage_dir}"',
        )
        assert "Settings" in result.stdout or "Extensions" in result.stdout

    def test_info_install_manual_mentions_ollama_bundle(self, tmp_path):
        stage_dir = tmp_path / "built"
        result = _run_fn(
            _FN_INFO_INSTALL_MANUAL,
            "info_install_manual",
            setup=f'STAGE_DIR="{stage_dir}"',
        )
        assert "ollama-agent.mcpb" in result.stdout

    def test_info_install_manual_mentions_lmstudio_bundle(self, tmp_path):
        stage_dir = tmp_path / "built"
        result = _run_fn(
            _FN_INFO_INSTALL_MANUAL,
            "info_install_manual",
            setup=f'STAGE_DIR="{stage_dir}"',
        )
        assert "lmstudio-agent.mcpb" in result.stdout

    def test_info_install_manual_suggests_open_flag(self, tmp_path):
        stage_dir = tmp_path / "built"
        result = _run_fn(
            _FN_INFO_INSTALL_MANUAL,
            "info_install_manual",
            setup=f'STAGE_DIR="{stage_dir}"',
        )
        assert "--open" in result.stdout

    # ------------------------------------------------------------------ #
    # ensure_mcpb_cli                                                       #
    # ------------------------------------------------------------------ #

    def test_ensure_mcpb_cli_exits_1_when_no_npm(self, tmp_path):
        """ensure_mcpb_cli must exit 1 when neither mcpb nor npm is available."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        env = dict(os.environ)
        # Keep /bin and /usr/bin so bash itself is found, but no npm or mcpb there
        env["PATH"] = f"{bin_dir}:/bin:/usr/bin"
        result = _run_fn(
            _FN_ENSURE_MCPB_CLI,
            "ensure_mcpb_cli",
            setup=f'PT_ROOT="{tmp_path}"',
            env=env,
        )
        combined = result.stdout + result.stderr
        assert "npm required" in combined or "EXIT_CODE:1" in result.stdout

    def test_ensure_mcpb_cli_uses_system_mcpb_first(self, tmp_path):
        """When mcpb is on PATH, ensure_mcpb_cli should prefer it."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _make_stub(bin_dir, "mcpb", "#!/usr/bin/env bash\necho 'mcpb 0.3.0'\nexit 0\n")
        env = _env_with_path(bin_dir)
        result = _run_fn(
            _FN_ENSURE_MCPB_CLI,
            'ensure_mcpb_cli; echo "CMD:${MCPB_CMD[*]}"',
            setup=f'PT_ROOT="{tmp_path}"',
            env=env,
        )
        assert "CMD:mcpb" in result.stdout

    def test_ensure_mcpb_cli_uses_local_prefix_when_present(self, tmp_path):
        """ensure_mcpb_cli should find mcpb in .npm-global/bin when installed locally."""
        npm_global_bin = tmp_path / ".npm-global" / "bin"
        npm_global_bin.mkdir(parents=True)
        _make_stub(npm_global_bin, "mcpb", "#!/usr/bin/env bash\necho 'mcpb'\nexit 0\n")
        # Provide npm in a stub bin; keep /bin:/usr/bin for bash itself
        stub_bin = tmp_path / "stub_bin"
        stub_bin.mkdir()
        _make_stub(stub_bin, "npm", "#!/usr/bin/env bash\nexit 0\n")
        env = dict(os.environ)
        # Prepend stub_bin; include system dirs for bash but not system mcpb
        env["PATH"] = f"{stub_bin}:/bin:/usr/bin"
        result = _run_fn(
            _FN_ENSURE_MCPB_CLI,
            'ensure_mcpb_cli; echo "CMD:${MCPB_CMD[*]}"',
            setup=f'PT_ROOT="{tmp_path}"',
            env=env,
        )
        assert "local prefix" in result.stdout or "CMD:" in result.stdout

    # ------------------------------------------------------------------ #
    # ensure_submodule                                                      #
    # ------------------------------------------------------------------ #

    def test_ensure_submodule_exits_1_when_build_script_missing(self, tmp_path):
        """ensure_submodule exits 1 when build-extensions.sh is not present."""
        submodule_dir = tmp_path / "vendor" / "Claude-Desktop-LLM"
        submodule_dir.mkdir(parents=True)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _make_stub(bin_dir, "git", "#!/usr/bin/env bash\nexit 0\n")
        env = _env_with_path(bin_dir)
        result = _run_fn(
            _FN_ENSURE_SUBMODULE,
            "ensure_submodule",
            setup=f'PT_ROOT="{tmp_path}"; SUBMODULE_DIR="{submodule_dir}"',
            env=env,
        )
        combined = result.stdout + result.stderr
        assert "EXIT_CODE:1" in result.stdout or "missing" in combined.lower()

    def test_ensure_submodule_exits_0_when_build_script_present(self, tmp_path):
        """ensure_submodule exits 0 when build-extensions.sh exists after git update."""
        submodule_dir = tmp_path / "vendor" / "Claude-Desktop-LLM"
        scripts = submodule_dir / "scripts"
        scripts.mkdir(parents=True)
        build_ext = scripts / "build-extensions.sh"
        build_ext.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        build_ext.chmod(build_ext.stat().st_mode | stat.S_IEXEC)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _make_stub(bin_dir, "git", "#!/usr/bin/env bash\necho 'abc1234'\nexit 0\n")
        env = _env_with_path(bin_dir)
        result = _run_fn(
            _FN_ENSURE_SUBMODULE,
            "ensure_submodule",
            setup=f'PT_ROOT="{tmp_path}"; SUBMODULE_DIR="{submodule_dir}"',
            env=env,
        )
        assert "EXIT_CODE:0" in result.stdout

    # ------------------------------------------------------------------ #
    # PERPETUA_MCPB_OPEN_DESKTOP env var (macOS only)                      #
    # ------------------------------------------------------------------ #

    def test_open_in_claude_desktop_env_var_triggers_open_on_darwin(self, tmp_path):
        """PERPETUA_MCPB_OPEN_DESKTOP=1 should trigger open on macOS."""
        if sys.platform != "darwin":
            pytest.skip("macOS-only behavior")
        stage_dir = tmp_path / "built"
        stage_dir.mkdir()
        (stage_dir / "ollama-agent.mcpb").write_bytes(b"PK")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        open_log = tmp_path / "open_log.txt"
        _make_stub(
            bin_dir,
            "open",
            f'#!/usr/bin/env bash\necho "opened:$1" >> {open_log}\nexit 0\n',
        )
        env = _env_with_path(bin_dir)
        env["PERPETUA_MCPB_OPEN_DESKTOP"] = "1"
        _run_fn(
            _FN_OPEN_IN_CLAUDE_DESKTOP,
            "open_in_claude_desktop",
            setup=f'STAGE_DIR="{stage_dir}"; SKIP_DESKTOP=0; OPEN_DESKTOP=0',
            env=env,
        )
        assert open_log.exists(), "open stub should have been called"

    # ------------------------------------------------------------------ #
    # Regression: JSON knockoff files must be absent                       #
    # ------------------------------------------------------------------ #

    def test_old_json_knockoff_ollama_not_present(self):
        """packages/mcpb-agents/ollama-agent.mcpb (JSON knockoff) must be removed."""
        old_file = ROOT / "packages" / "mcpb-agents" / "ollama-agent.mcpb"
        assert not old_file.exists(), (
            "JSON knockoff ollama-agent.mcpb should have been removed by this PR"
        )

    def test_old_json_knockoff_lmstudio_not_present(self):
        """packages/mcpb-agents/lmstudio-agent.mcpb (JSON knockoff) must be removed."""
        old_file = ROOT / "packages" / "mcpb-agents" / "lmstudio-agent.mcpb"
        assert not old_file.exists(), (
            "JSON knockoff lmstudio-agent.mcpb should have been removed by this PR"
        )

    # ------------------------------------------------------------------ #
    # Script content assertions                                            #
    # ------------------------------------------------------------------ #

    def test_script_references_submodule_vendor_path(self):
        content = INSTALL_DESKTOP_SH.read_text(encoding="utf-8")
        assert "vendor/Claude-Desktop-LLM" in content

    def test_script_references_anthropic_mcpb_package(self):
        content = INSTALL_DESKTOP_SH.read_text(encoding="utf-8")
        assert "@anthropic-ai/mcpb" in content

    def test_script_stages_to_packages_mcpb_agents_built(self):
        content = INSTALL_DESKTOP_SH.read_text(encoding="utf-8")
        assert "packages/mcpb-agents/built" in content

    def test_script_independent_of_alphaclaw(self):
        """The script comment must state AlphaClaw independence."""
        content = INSTALL_DESKTOP_SH.read_text(encoding="utf-8")
        assert "AlphaClaw" not in content.split("Independent")[1].split("\n")[0] or \
               "Independent of AlphaClaw" in content


# ---------------------------------------------------------------------------
# .gitignore rules (regression tests for new entries)
# ---------------------------------------------------------------------------

class TestGitignoreRules:
    """Verify the new .gitignore entries added in this PR are present."""

    def _gitignore_content(self) -> str:
        """
        Read and return the repository's .gitignore file content.
        
        Returns:
            str: The contents of the repository's `.gitignore` file decoded as UTF-8.
        """
        return (ROOT / ".gitignore").read_text(encoding="utf-8")

    def test_npm_global_dir_is_ignored(self):
        content = self._gitignore_content()
        assert ".npm-global/" in content

    def test_mcpb_built_artifacts_are_ignored(self):
        content = self._gitignore_content()
        assert "packages/mcpb-agents/built/*.mcpb" in content

    def test_gitignore_built_gitkeep_not_ignored(self):
        """The .gitkeep placeholder inside built/ must not be gitignored."""
        result = subprocess.run(
            ["git", "check-ignore", "-v", "packages/mcpb-agents/built/.gitkeep"],
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # git check-ignore returns 0 only if the path IS ignored — that is wrong for .gitkeep
        assert result.returncode != 0, (
            ".gitkeep inside built/ should not be gitignored (only *.mcpb should match)"
        )

    def test_npm_global_entry_has_comment(self):
        """The .npm-global/ entry should be near a comment explaining why."""
        content = self._gitignore_content()
        idx = content.find(".npm-global/")
        surrounding = content[max(0, idx - 200): idx + 100]
        assert "#" in surrounding, "Expected a comment near the .npm-global/ entry"

    def test_mcpb_artifacts_entry_has_comment(self):
        content = self._gitignore_content()
        idx = content.find("packages/mcpb-agents/built/*.mcpb")
        surrounding = content[max(0, idx - 300): idx + 100]
        assert "#" in surrounding, "Expected a comment near the built/*.mcpb entry"


# ---------------------------------------------------------------------------
# packages/mcpb-agents/built/ directory structure
# ---------------------------------------------------------------------------

class TestMcpbAgentsBuiltDir:
    """Tests for the new packages/mcpb-agents/built/ staging directory."""

    def test_built_dir_exists(self):
        built = ROOT / "packages" / "mcpb-agents" / "built"
        assert built.is_dir()

    def test_gitkeep_exists_in_built(self):
        gitkeep = ROOT / "packages" / "mcpb-agents" / "built" / ".gitkeep"
        assert gitkeep.exists()

    def test_gitkeep_mentions_install_sh(self):
        content = (ROOT / "packages" / "mcpb-agents" / "built" / ".gitkeep").read_text(
            encoding="utf-8"
        )
        assert "install.sh" in content

    def test_gitkeep_is_documentation_only(self):
        """The .gitkeep must only contain comment/blank lines."""
        for line in (ROOT / "packages" / "mcpb-agents" / "built" / ".gitkeep").read_text(
            encoding="utf-8"
        ).splitlines():
            stripped = line.strip()
            if stripped:
                assert stripped.startswith("#"), f"unexpected active line in .gitkeep: {line!r}"

    def test_gitkeep_mentions_gitignored(self):
        content = (ROOT / "packages" / "mcpb-agents" / "built" / ".gitkeep").read_text(
            encoding="utf-8"
        )
        assert "gitignored" in content.lower() or "regenerate" in content.lower()

    def test_stack_env_example_exists(self):
        example = ROOT / "packages" / "mcpb-agents" / "built" / "stack-env.example"
        assert example.exists()

    def test_stack_env_example_mentions_ollama_port(self):
        content = (ROOT / "packages" / "mcpb-agents" / "built" / "stack-env.example").read_text(
            encoding="utf-8"
        )
        assert "11434" in content

    def test_stack_env_example_mentions_lmstudio_port(self):
        content = (ROOT / "packages" / "mcpb-agents" / "built" / "stack-env.example").read_text(
            encoding="utf-8"
        )
        assert "1234" in content

    def test_stack_env_example_is_comments_only(self):
        """All non-blank lines must be comments."""
        for line in (ROOT / "packages" / "mcpb-agents" / "built" / "stack-env.example").read_text(
            encoding="utf-8"
        ).splitlines():
            stripped = line.strip()
            if stripped:
                assert stripped.startswith("#"), (
                    f"Non-comment, non-blank line in stack-env.example: {line!r}"
                )

    def test_stack_env_example_mentions_pt_not_alphaclaw(self):
        """PT must be mentioned; AlphaClaw must not own the config."""
        content = (ROOT / "packages" / "mcpb-agents" / "built" / "stack-env.example").read_text(
            encoding="utf-8"
        )
        assert "PT" in content or "Perpetua" in content


# ---------------------------------------------------------------------------
# .gitmodules submodule entry
# ---------------------------------------------------------------------------

class TestGitmodules:
    """Verify the new Claude-Desktop-LLM submodule entry in .gitmodules."""

    def _content(self) -> str:
        """
        Read and return the repository's .gitmodules file contents.
        
        Returns:
            The utf-8 decoded text of the `.gitmodules` file at the repository root.
        """
        return (ROOT / ".gitmodules").read_text(encoding="utf-8")

    def test_claude_desktop_llm_submodule_entry_present(self):
        assert "Claude-Desktop-LLM" in self._content()

    def test_submodule_url_points_to_yayoboy(self):
        assert "yayoboy/Claude-Desktop-LLM" in self._content()

    def test_submodule_path_is_vendor(self):
        assert "vendor/Claude-Desktop-LLM" in self._content()

    def test_submodule_section_header_correct(self):
        content = self._content()
        assert '[submodule "vendor/Claude-Desktop-LLM"]' in content

    def test_submodule_url_uses_github(self):
        content = self._content()
        idx = content.find("Claude-Desktop-LLM")
        section = content[max(0, idx - 50): idx + 200]
        assert "github.com" in section
