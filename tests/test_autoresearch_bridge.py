"""test_autoresearch_bridge.py — Unit tests for orchestrator/autoresearch_bridge.py

Tests SwarmState parsing, GPU lock helpers, swarm_state.md initialisation,
the preflight convenience function, and the new plugin install helper.
All SSH/scp/claude calls are mocked — no GPU runner required.
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import orchestrator.autoresearch_bridge as bridge
from orchestrator.autoresearch_bridge import (
    AUTORESEARCH_DEFAULT_BRANCH,
    AUTORESEARCH_REMOTE,
    SwarmState,
    SyncResult,
    init_swarm_state,
    is_gpu_idle,
    read_swarm_state,
)


@pytest.fixture(autouse=True)
def patch_swarm_path(tmp_path, monkeypatch):
    """Redirect swarm_state.md to a temp directory so tests are isolated."""
    fake_local = tmp_path / "autoresearch"
    fake_local.mkdir()
    monkeypatch.setattr(bridge, "LOCAL_REPO_PATH", fake_local)
    monkeypatch.setattr(bridge, "SWARM_STATE_FILE", fake_local / "swarm_state.md")
    return fake_local


# ── module-level constant assertions ─────────────────────────────────────────

class TestModuleConstants:
    @pytest.fixture(autouse=True)
    def restore_bridge_module(self):
        """Reload bridge to defaults before each test in this class.

        Env-override tests call importlib.reload(), which mutates the module
        in-place. This fixture ensures isolation between those tests.
        """
        import importlib
        importlib.reload(bridge)
        yield
        importlib.reload(bridge)

    def test_autoresearch_remote_contains_uditgoenka(self):
        """AUTORESEARCH_REMOTE must default to uditgoenka fork, not karpathy."""
        assert "uditgoenka/autoresearch" in bridge.AUTORESEARCH_REMOTE

    def test_autoresearch_remote_not_karpathy(self):
        assert "karpathy" not in bridge.AUTORESEARCH_REMOTE

    def test_autoresearch_default_branch_is_main(self):
        """Default branch must be 'main', not 'master'."""
        assert bridge.AUTORESEARCH_DEFAULT_BRANCH == "main"

    def test_autoresearch_remote_env_override(self, monkeypatch):
        """AUTORESEARCH_REMOTE should be overridable via env var."""
        import importlib
        monkeypatch.setenv("AUTORESEARCH_REMOTE",
                           "https://github.com/myorg/autoresearch.git")
        bridge_fresh = importlib.reload(bridge)
        assert "myorg/autoresearch" in bridge_fresh.AUTORESEARCH_REMOTE

    def test_autoresearch_branch_env_override(self, monkeypatch):
        import importlib
        monkeypatch.setenv("AUTORESEARCH_BRANCH", "dev")
        bridge_fresh = importlib.reload(bridge)
        assert bridge_fresh.AUTORESEARCH_DEFAULT_BRANCH == "dev"


# ── SwarmState parsing ────────────────────────────────────────────────────────

class TestReadSwarmState:
    def test_returns_idle_when_file_absent(self):
        state = read_swarm_state()
        assert state.gpu_status == "IDLE"

    def test_parses_gpu_busy(self):
        content = textwrap.dedent("""\
            ## Status
            - GPU: BUSY
        """)
        bridge.SWARM_STATE_FILE.write_text(content, encoding="utf-8")
        state = read_swarm_state()
        assert state.gpu_status == "BUSY"

    def test_parses_gpu_idle(self):
        bridge.SWARM_STATE_FILE.write_text("- GPU: IDLE\n", encoding="utf-8")
        assert read_swarm_state().gpu_status == "IDLE"

    def test_parses_val_bpb(self):
        bridge.SWARM_STATE_FILE.write_text("val_bpb: 1.234\n", encoding="utf-8")
        assert read_swarm_state().baseline_val_bpb == pytest.approx(1.234)

    def test_parses_git_sha(self):
        bridge.SWARM_STATE_FILE.write_text("git_sha: abcdef1234567890\n", encoding="utf-8")
        assert read_swarm_state().baseline_sha == "abcdef1234567890"

    def test_invalid_val_bpb_ignored(self):
        bridge.SWARM_STATE_FILE.write_text("val_bpb: not_a_number\n", encoding="utf-8")
        assert read_swarm_state().baseline_val_bpb == 0.0


# ── GPU lock helpers ──────────────────────────────────────────────────────────

class TestIsGpuIdle:
    def test_idle_when_no_file(self):
        assert is_gpu_idle() is True

    def test_idle_when_status_idle(self):
        bridge.SWARM_STATE_FILE.write_text("- GPU: IDLE\n", encoding="utf-8")
        assert is_gpu_idle() is True

    def test_not_idle_when_busy(self):
        bridge.SWARM_STATE_FILE.write_text("- GPU: BUSY\n", encoding="utf-8")
        assert is_gpu_idle() is False

    def test_case_insensitive(self):
        bridge.SWARM_STATE_FILE.write_text("- GPU: idle\n", encoding="utf-8")
        assert is_gpu_idle() is True


# ── init_swarm_state ──────────────────────────────────────────────────────────

class TestInitSwarmState:
    def test_creates_file(self):
        init_swarm_state("test-run")
        assert bridge.SWARM_STATE_FILE.exists()

    def test_file_contains_run_tag(self):
        init_swarm_state("mar22")
        assert "mar22" in bridge.SWARM_STATE_FILE.read_text(encoding="utf-8")

    def test_file_starts_with_idle_status(self):
        init_swarm_state("myrun")
        assert "GPU: IDLE" in bridge.SWARM_STATE_FILE.read_text(encoding="utf-8")

    def test_file_contains_managed_by_comment(self):
        init_swarm_state("anyrun")
        assert "autoresearch_bridge.py" in bridge.SWARM_STATE_FILE.read_text(encoding="utf-8")

    def test_file_contains_hardware_guard(self):
        """swarm_state.md must carry the Windows sequential-load reminder."""
        init_swarm_state("guard-test")
        content = bridge.SWARM_STATE_FILE.read_text(encoding="utf-8")
        assert "HARDWARE GUARD" in content or "strictly sequential" in content.lower()


# ── SyncResult dataclass ──────────────────────────────────────────────────────

class TestSyncResult:
    def test_ok_result(self):
        r = SyncResult(ok=True, sha="abc123")
        assert r.ok is True and r.sha == "abc123" and r.error == ""

    def test_error_result(self):
        r = SyncResult(ok=False, error="SSH timeout")
        assert r.ok is False and r.error == "SSH timeout"


# ── sync_autoresearch_idempotent ──────────────────────────────────────────────

class TestSyncAutoresearchIdempotent:
    def test_uses_default_branch_not_master(self):
        """SSH command must reference bridge.AUTORESEARCH_DEFAULT_BRANCH, not 'master'."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "HEAD sha\nabc123def"
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            bridge.sync_autoresearch_idempotent()
        called_args = mock_run.call_args[0][0]
        ssh_cmd = " ".join(called_args)
        assert "master" not in ssh_cmd, "SSH command must not hardcode 'master'"
        # Verify the actual module constant (not a cached import-time value)
        assert bridge.AUTORESEARCH_DEFAULT_BRANCH in ssh_cmd

    def test_returns_sync_result_on_success(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "HEAD sha\nabc123def"
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            result = bridge.sync_autoresearch_idempotent()
        assert result.ok is True
        assert result.sha == "abc123def"

    def test_returns_error_on_nonzero_returncode(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "fatal: not a git repository"
        with patch("subprocess.run", return_value=mock_result):
            result = bridge.sync_autoresearch_idempotent()
        assert result.ok is False
        assert "not a git repository" in result.error

    def test_returns_error_on_timeout(self):
        import subprocess
        with patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired("ssh", 90)):
            result = bridge.sync_autoresearch_idempotent()
        assert result.ok is False
        assert "timeout" in result.error.lower()


# ── install_autoresearch_plugin ───────────────────────────────────────────────

class TestInstallAutoresearchPlugin:
    def test_skips_if_already_installed(self):
        """Plugin install is idempotent: skip when plugin list contains it."""
        mock_list = MagicMock(returncode=0,
                              stdout="uditgoenka/autoresearch  v1.0.0\n",
                              stderr="")
        with patch("subprocess.run", return_value=mock_list) as mock_run:
            result = bridge.install_autoresearch_plugin()
        assert result.ok is True
        assert result.sha == "already-installed"
        assert mock_run.call_count == 1   # only list, no install

    def test_runs_two_commands_when_not_installed(self):
        """When plugin is absent, runs marketplace add + plugin install."""
        mock_list    = MagicMock(returncode=0, stdout="other-plugin\n", stderr="")
        mock_add     = MagicMock(returncode=0, stdout="", stderr="")
        mock_install = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run",
                   side_effect=[mock_list, mock_add, mock_install]) as mock_run:
            result = bridge.install_autoresearch_plugin()
        assert result.ok is True
        commands = [" ".join(c[0][0]) for c in mock_run.call_args_list]
        assert any("marketplace" in c and "uditgoenka/autoresearch" in c
                   for c in commands)
        assert any("plugin install" in c for c in commands)

    def test_returns_error_if_marketplace_add_fails(self):
        mock_list = MagicMock(returncode=0, stdout="", stderr="")
        mock_add  = MagicMock(returncode=1, stdout="", stderr="network error")
        with patch("subprocess.run", side_effect=[mock_list, mock_add]):
            result = bridge.install_autoresearch_plugin()
        assert result.ok is False
        assert "marketplace add failed" in result.error


# ── preflight ─────────────────────────────────────────────────────────────────

class TestPreflight:
    def test_preflight_initialises_swarm_state_when_absent(self):
        with patch.object(bridge, "install_autoresearch_plugin",
                          return_value=SyncResult(ok=True)), \
             patch.object(bridge, "bootstrap_autoresearch_on_runner",
                          return_value=SyncResult(ok=True, sha="abc")):
            result = bridge.preflight(run_tag="testrun")
        assert result["swarm_state_initialised"] is True
        assert bridge.SWARM_STATE_FILE.exists()

    def test_preflight_skips_init_when_file_exists(self):
        bridge.SWARM_STATE_FILE.write_text("existing content", encoding="utf-8")
        with patch.object(bridge, "install_autoresearch_plugin",
                          return_value=SyncResult(ok=True)), \
             patch.object(bridge, "bootstrap_autoresearch_on_runner",
                          return_value=SyncResult(ok=True, sha="abc")):
            result = bridge.preflight(run_tag="testrun")
        assert result["swarm_state_initialised"] is False

    def test_preflight_returns_sync_ok_on_success(self):
        with patch.object(bridge, "install_autoresearch_plugin",
                          return_value=SyncResult(ok=True)), \
             patch.object(bridge, "bootstrap_autoresearch_on_runner",
                          return_value=SyncResult(ok=True, sha="deadbeef")):
            result = bridge.preflight()
        assert result["sync_ok"] is True
        assert result["sha"] == "deadbeef"

    def test_preflight_propagates_sync_failure(self):
        with patch.object(bridge, "install_autoresearch_plugin",
                          return_value=SyncResult(ok=True)), \
             patch.object(bridge, "bootstrap_autoresearch_on_runner",
                          return_value=SyncResult(ok=False, error="SSH refused")):
            result = bridge.preflight()
        assert result["sync_ok"] is False
        assert result["error"] == "SSH refused"

    def test_preflight_exposes_plugin_ok(self):
        with patch.object(bridge, "install_autoresearch_plugin",
                          return_value=SyncResult(ok=False, error="no claude CLI")), \
             patch.object(bridge, "bootstrap_autoresearch_on_runner",
                          return_value=SyncResult(ok=True, sha="abc")):
            result = bridge.preflight()
        assert result["plugin_ok"] is False
        assert "no claude CLI" in result["plugin_error"]
