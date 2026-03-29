"""test_autoresearch_bridge.py — Unit tests for orchestrator/autoresearch_bridge.py

Tests SwarmState parsing, GPU lock helpers, swarm_state.md initialisation,
and the preflight convenience function.
All SSH/scp calls are mocked — no GPU runner required.
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import orchestrator.autoresearch_bridge as bridge
from orchestrator.autoresearch_bridge import (
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


class TestReadSwarmState:
    def test_returns_idle_when_file_absent(self):
        state = read_swarm_state()
        assert state.gpu_status == "IDLE"

    def test_parses_gpu_busy(self, tmp_path):
        content = textwrap.dedent("""\
            ## Status
            - GPU: BUSY
        """)
        bridge.SWARM_STATE_FILE.write_text(content, encoding="utf-8")
        state = read_swarm_state()
        assert state.gpu_status == "BUSY"

    def test_parses_gpu_idle(self):
        content = "- GPU: IDLE\n"
        bridge.SWARM_STATE_FILE.write_text(content, encoding="utf-8")
        state = read_swarm_state()
        assert state.gpu_status == "IDLE"

    def test_parses_val_bpb(self):
        content = "val_bpb: 1.234\n"
        bridge.SWARM_STATE_FILE.write_text(content, encoding="utf-8")
        state = read_swarm_state()
        assert state.baseline_val_bpb == pytest.approx(1.234)

    def test_parses_git_sha(self):
        content = "git_sha: abcdef1234567890\n"
        bridge.SWARM_STATE_FILE.write_text(content, encoding="utf-8")
        state = read_swarm_state()
        assert state.baseline_sha == "abcdef1234567890"

    def test_invalid_val_bpb_ignored(self):
        content = "val_bpb: not_a_number\n"
        bridge.SWARM_STATE_FILE.write_text(content, encoding="utf-8")
        state = read_swarm_state()
        assert state.baseline_val_bpb == 0.0


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


class TestInitSwarmState:
    def test_creates_file(self):
        init_swarm_state("test-run")
        assert bridge.SWARM_STATE_FILE.exists()

    def test_file_contains_run_tag(self):
        init_swarm_state("mar22")
        content = bridge.SWARM_STATE_FILE.read_text(encoding="utf-8")
        assert "mar22" in content

    def test_file_starts_with_idle_status(self):
        init_swarm_state("myrun")
        content = bridge.SWARM_STATE_FILE.read_text(encoding="utf-8")
        assert "GPU: IDLE" in content

    def test_file_contains_managed_by_comment(self):
        init_swarm_state("anyrun")
        content = bridge.SWARM_STATE_FILE.read_text(encoding="utf-8")
        assert "autoresearch_bridge.py" in content


class TestSyncResult:
    def test_ok_result(self):
        r = SyncResult(ok=True, sha="abc123")
        assert r.ok is True
        assert r.sha == "abc123"
        assert r.error == ""

    def test_error_result(self):
        r = SyncResult(ok=False, error="SSH timeout")
        assert r.ok is False
        assert r.error == "SSH timeout"


class TestSyncAutoresearchIdempotent:
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
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ssh", 90)):
            result = bridge.sync_autoresearch_idempotent()
        assert result.ok is False
        assert "timeout" in result.error.lower()


class TestPreflight:
    def test_preflight_initialises_swarm_state_when_absent(self):
        with patch.object(bridge, "bootstrap_autoresearch_on_runner",
                          return_value=SyncResult(ok=True, sha="abc")):
            result = bridge.preflight(run_tag="testrun")
        assert result["swarm_state_initialised"] is True
        assert bridge.SWARM_STATE_FILE.exists()

    def test_preflight_skips_init_when_file_exists(self):
        bridge.SWARM_STATE_FILE.write_text("existing content", encoding="utf-8")
        with patch.object(bridge, "bootstrap_autoresearch_on_runner",
                          return_value=SyncResult(ok=True, sha="abc")):
            result = bridge.preflight(run_tag="testrun")
        assert result["swarm_state_initialised"] is False

    def test_preflight_returns_sync_ok_on_success(self):
        with patch.object(bridge, "bootstrap_autoresearch_on_runner",
                          return_value=SyncResult(ok=True, sha="deadbeef")):
            result = bridge.preflight()
        assert result["sync_ok"] is True
        assert result["sha"] == "deadbeef"

    def test_preflight_propagates_sync_failure(self):
        with patch.object(bridge, "bootstrap_autoresearch_on_runner",
                          return_value=SyncResult(ok=False, error="SSH refused")):
            result = bridge.preflight()
        assert result["sync_ok"] is False
        assert result["error"] == "SSH refused"
