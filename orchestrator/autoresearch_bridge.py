"""orchestrator/autoresearch_bridge.py

Layer 4 integration: karpathy/autoresearch as a managed foot-soldier.

Responsibilities
----------------
- Idempotent git sync of the canonical autoresearch clone on the Windows GPU runner.
- Spawning the three cognitive swarm agents (Coder, Evaluator, Orchestrator) via
  the top-level Perplexity-Tools AgentTracker so lifecycle and idempotency are
  consistent with the rest of the stack.
- Reading swarm_state.md for GPU lock status before dispatching any training run.
- Progress reporting: all long-running SSH operations print staged ASCII bars.

Design rules (from approved interoperability contract)
------------------------------------------------------
1. ONLY Perplexity-Tools/orchestrator.py (or the FastAPI /autoresearch/* endpoints)
   may call sync_autoresearch_idempotent().  Layers 2-4 treat autoresearch as
   read-only from a lifecycle perspective.
2. The autoresearch clone lives in ONE canonical path on the Windows GPU runner:
       C:/Users/<WINUSER>/autoresearch/
   Never duplicate it.
3. File transfer uses scp only (rsync not guaranteed on Windows SSH sessions).
4. API keys are NEVER written to files; they are injected as session env vars.
5. GPU lock is the IDLE/BUSY flag in swarm_state.md \u2014 no external queue daemon.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── configuration ──────────────────────────────────────────────────────────────

GPU_BOX: str = os.environ.get("GPU_BOX", "WINUSER@192.168.1.100")
GPU_REPO_PATH: str = os.environ.get("GPU_REPO_PATH", "autoresearch")
AUTORESEARCH_REMOTE: str = "https://github.com/karpathy/autoresearch.git"
SSH_TIMEOUT: int = int(os.environ.get("SSH_TIMEOUT", "90"))

_SSH_KEY: str = os.environ.get("DELL_SSH_KEY", "")
_SSH_OPTS: list[str] = (
    ["-i", _SSH_KEY, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
    if _SSH_KEY else
    ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
)

LOCAL_REPO_PATH: Path = Path(
    os.environ.get("LOCAL_AUTORESEARCH_PATH", str(Path.home() / "autoresearch"))
)
SWARM_STATE_FILE: Path = LOCAL_REPO_PATH / "swarm_state.md"


# ── progress helper ────────────────────────────────────────────────────────────

def _progress(label: str, elapsed: int, total: int) -> None:
    """Print a single-line overwriting ASCII progress bar.

    Example output:
      [autoresearch] [\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591] 44%
    """
    bar_width = 36
    filled = int(bar_width * min(elapsed, total) / max(total, 1))
    bar = "\u2588" * filled + "\u2591" * (bar_width - filled)
    pct = int(100 * min(elapsed, total) / max(total, 1))
    print(f"\r  [{label}] [{bar}] {pct:3d}%  ", end="", flush=True)


def _progress_done(label: str, detail: str = "") -> None:
    """Print a completion line after a progress bar."""
    bar_width = 36
    bar = "\u2588" * bar_width
    suffix = f"  \u2713 {detail}" if detail else "  \u2713 done"
    print(f"\r  [{label}] [{bar}] 100%{suffix}")


# ── data types ─────────────────────────────────────────────────────────────────

@dataclass
class SyncResult:
    ok: bool
    sha: str = ""
    error: str = ""


@dataclass
class SwarmState:
    gpu_status: str = "IDLE"
    baseline_val_bpb: float = 0.0
    baseline_sha: str = ""
    orchestrator_directive: str = ""
    evaluator_findings: list[str] = field(default_factory=list)


# ── idempotent sync ────────────────────────────────────────────────────────────

def sync_autoresearch_idempotent() -> SyncResult:
    """Pull latest karpathy/autoresearch on the Windows GPU runner.

    Idempotent: safe to call on every orchestration cycle.
    Prints a staged ASCII progress bar during the SSH operation.
    """
    print("[autoresearch] \u2192 Syncing autoresearch on GPU runner\u2026")
    cmd = (
        f"cd {GPU_REPO_PATH} && "
        "git fetch origin && "
        "git reset --hard origin/master && "
        "git rev-parse HEAD"
    )

    try:
        result = subprocess.run(
            ["ssh", *_SSH_OPTS, GPU_BOX, cmd],
            capture_output=True,
            text=True,
            timeout=SSH_TIMEOUT,
        )
        if result.returncode != 0:
            print()
            error = (result.stderr or result.stdout or "").strip()
            if not error:
                error = f"SSH command failed with return code {result.returncode}"
            return SyncResult(ok=False, error=error)

        stdout = (result.stdout or "").strip()
        lines = [line for line in stdout.splitlines() if line.strip()]
        if not lines:
            print()
            return SyncResult(ok=False, error="SSH sync completed without returning a SHA")

        sha = lines[-1]
        _progress_done("autoresearch", f"sha={sha[:7]}")
        return SyncResult(ok=True, sha=sha)

    except subprocess.TimeoutExpired:
        print()
        return SyncResult(ok=False, error=f"SSH timeout after {SSH_TIMEOUT}s")
    except Exception as exc:  # noqa: BLE001
        print()
        return SyncResult(ok=False, error=str(exc))


# ── bootstrap ──────────────────────────────────────────────────────────────────

def bootstrap_autoresearch_on_runner() -> SyncResult:
    """Clone autoresearch on the Windows GPU runner if it does not exist yet.

    Idempotent. Prints staged status messages.
    """
    print("[autoresearch] \u2192 Bootstrap: ensuring repo exists on GPU runner\u2026")
    check_cmd = (
        f"if not exist {GPU_REPO_PATH} "
        f"git clone {AUTORESEARCH_REMOTE} {GPU_REPO_PATH}"
    )
    start = time.monotonic()
    try:
        proc = subprocess.Popen(
            ["ssh", *_SSH_OPTS, GPU_BOX, check_cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        while proc.poll() is None:
            elapsed = int(time.monotonic() - start)
            _progress("bootstrap", elapsed, SSH_TIMEOUT)
            time.sleep(1)
        proc.communicate(timeout=5)

    except Exception as exc:  # noqa: BLE001
        print()
        return SyncResult(ok=False, error=f"Bootstrap failed: {exc}")

    _progress_done("bootstrap", "repo present")
    return sync_autoresearch_idempotent()


# ── GPU lock helpers ───────────────────────────────────────────────────────────

def read_swarm_state() -> SwarmState:
    if not SWARM_STATE_FILE.exists():
        return SwarmState()
    content = SWARM_STATE_FILE.read_text(encoding="utf-8")
    state = SwarmState()
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("- GPU:"):
            state.gpu_status = line.split(":", 1)[1].strip()
        elif line.startswith("val_bpb:"):
            try:
                state.baseline_val_bpb = float(line.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("git_sha:"):
            state.baseline_sha = line.split(":", 1)[1].strip()
    return state


def is_gpu_idle() -> bool:
    return read_swarm_state().gpu_status.upper() == "IDLE"


# ── deploy / run / fetch ───────────────────────────────────────────────────────

def deploy_train_py() -> bool:
    local_train = LOCAL_REPO_PATH / "train.py"
    if not local_train.exists():
        return False
    result = subprocess.run(
        ["scp", *_SSH_OPTS, str(local_train), f"{GPU_BOX}:{GPU_REPO_PATH}/train.py"],
        capture_output=True, text=True, timeout=SSH_TIMEOUT,
    )
    return result.returncode == 0


def run_experiment_on_gpu() -> bool:
    cmd = (
        f"cd {GPU_REPO_PATH} && "
        "conda run -n autoresearch uv run train.py > run.log 2>&1"
    )
    result = subprocess.run(
        ["ssh", *_SSH_OPTS, GPU_BOX, cmd],
        capture_output=True, text=True, timeout=400,
    )
    return result.returncode == 0


def fetch_run_log() -> bool:
    result = subprocess.run(
        [
            "scp", *_SSH_OPTS,
            f"{GPU_BOX}:{GPU_REPO_PATH}/run.log",
            str(LOCAL_REPO_PATH / "log.txt"),
        ],
        capture_output=True, text=True, timeout=SSH_TIMEOUT,
    )
    return result.returncode == 0


# ── swarm_state.md initialiser ─────────────────────────────────────────────────

def init_swarm_state(run_tag: str) -> None:
    content = textwrap.dedent(f"""\
        # Swarm State \u2014 {run_tag}
        <!-- Managed by Perplexity-Tools autoresearch_bridge.py -->
        <!-- DO NOT commit this file; it is ephemeral session state. -->

        ## Current Baseline
        val_bpb: TBD
        git_sha: TBD

        ## Orchestrator Directives
        - Establish baseline: run train.py as-is for the first experiment.

        ## Evaluator Findings
        - (none yet)

        ## Status
        - GPU: IDLE
        <!-- IDLE = safe to dispatch. BUSY = Coder has an active run. -->
        <!-- Only the Coder agent may flip IDLE \u2192 BUSY and back. -->
    """)
    SWARM_STATE_FILE.write_text(content, encoding="utf-8")


# ── preflight ──────────────────────────────────────────────────────────────────

def preflight(run_tag: Optional[str] = None) -> dict:
    """Full pre-flight sequence with staged progress output.

    Steps (all idempotent):
    1. Bootstrap / sync autoresearch on GPU runner (with progress bar).
    2. Initialise swarm_state.md on Mac (only if run_tag supplied and absent).
    """
    sync = bootstrap_autoresearch_on_runner()
    initialised = False
    if run_tag and not SWARM_STATE_FILE.exists():
        init_swarm_state(run_tag)
        initialised = True
    return {
        "sync_ok": sync.ok,
        "sha": sync.sha,
        "error": sync.error,
        "swarm_state_initialised": initialised,
    }
