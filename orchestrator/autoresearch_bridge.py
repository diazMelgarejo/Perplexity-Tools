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
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── configuration (resolved from environment, never hard-coded secrets) ────────

# GPU_BOX: SSH target for the Windows RTX 3080.
# Uses detect_active_tilting_ip() host if GPU_BOX not set, but SSH needs user@host
# so we keep a separate env var.  Default reflects the current 192.168.254.x subnet.
GPU_BOX: str = os.environ.get("GPU_BOX", "WINUSER@192.168.254.100")
GPU_REPO_PATH: str = os.environ.get("GPU_REPO_PATH", "autoresearch")
AUTORESEARCH_REMOTE: str = "https://github.com/karpathy/autoresearch.git"
SSH_TIMEOUT: int = int(os.environ.get("SSH_TIMEOUT", "90"))

# WIN_SSH_KEY is the canonical name; DELL_SSH_KEY kept for backward-compat with
# existing .env files from before the subnet rename.
_SSH_KEY: str = os.environ.get("WIN_SSH_KEY") or os.environ.get("DELL_SSH_KEY", "")
_SSH_OPTS: list[str] = (
    ["-i", _SSH_KEY, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
    if _SSH_KEY else
    ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
)

# ── Hardware Overload Prevention (HOP) — win-rtx3080:1234 slot lock ───────────
# The RTX 3080 has limited VRAM.  Executor and Verifier/Critic agents both target
# LM Studio on this machine.  Loading a second model while the first is still in
# VRAM triggers repeated load/unload cycles that crash the GPU (see LESSONS.md
# 2026-04-07 "Rapid model reload after crash burns GPU").
# This lock serializes any call that holds the Windows LM Studio inference slot.
# CRASH_RECOVERY_SECS matches the 30 s cooldown already used by launch_researchers.
_WIN_LM_STUDIO_SLOT: threading.Lock = threading.Lock()
SLOT_ACQUIRE_TIMEOUT_SECS: int = int(os.environ.get("HOP_SLOT_TIMEOUT", "120"))
CRASH_RECOVERY_SECS: int = 30

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


# ── idempotent sync (called by orchestrator before EVERY autoresearch run) ───── 

def sync_autoresearch_idempotent() -> SyncResult:
    """Pull latest karpathy/autoresearch on the Windows GPU runner.

    Idempotent: safe to call on every orchestration cycle.
    Uses `git fetch + reset --hard origin/main` so the runner always
    runs the latest upstream code without merge conflicts.
    Returns SyncResult with HEAD sha for logging.
    Prints a staged ASCII progress bar during the SSH operation.
    """
    print("[autoresearch] \u2192 Syncing autoresearch on GPU runner\u2026")
    cmd = (
        f"cd {GPU_REPO_PATH} && "
        "git fetch origin && "
        "git reset --hard origin/master && "
        "git rev-parse HEAD"
    )

    # Run synchronously so tests can mock the SSH call deterministically.
    # The old animated progress loop depended on Popen polling, which also made
    # the unit tests hit the real host when subprocess.run was patched.
    try:
        result = subprocess.run(
            ["ssh", *_SSH_OPTS, GPU_BOX, cmd],
            capture_output=True,
            text=True,
            timeout=SSH_TIMEOUT,
        )
        if result.returncode != 0:
            print()
            # Prefer stderr, but fall back to stdout if the remote shell wrote
            # its failure there. Keep a deterministic message when both are empty.
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


# ── bootstrap: ensure the repo exists on the GPU runner (first-run only) ──────

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


# ── GPU lock helpers (read/write swarm_state.md on Mac) ───────────────────────

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
    """SCP train.py to the GPU runner.

    Uses the HOP slot lock so a Verifier/Critic that is mid-inference on the same
    Windows LM Studio endpoint cannot race with a new Coder dispatch.
    """
    local_train = LOCAL_REPO_PATH / "train.py"
    if not local_train.exists():
        return False
    acquired = _WIN_LM_STUDIO_SLOT.acquire(timeout=SLOT_ACQUIRE_TIMEOUT_SECS)
    if not acquired:
        print(f"[autoresearch] ⚠ HOP: deploy_train_py timed out waiting for win-lm-studio slot after {SLOT_ACQUIRE_TIMEOUT_SECS}s")
        return False
    try:
        result = subprocess.run(
            ["scp", *_SSH_OPTS, str(local_train), f"{GPU_BOX}:{GPU_REPO_PATH}/train.py"],
            capture_output=True, text=True, timeout=SSH_TIMEOUT,
        )
        return result.returncode == 0
    finally:
        _WIN_LM_STUDIO_SLOT.release()


def run_experiment_on_gpu() -> bool:
    """Dispatch the training run on the GPU runner.

    Holds the HOP slot for the full duration of the run so the Verifier/Critic
    waits before loading its own model onto the same VRAM.
    """
    acquired = _WIN_LM_STUDIO_SLOT.acquire(timeout=SLOT_ACQUIRE_TIMEOUT_SECS)
    if not acquired:
        print(f"[autoresearch] ⚠ HOP: run_experiment timed out waiting for win-lm-studio slot after {SLOT_ACQUIRE_TIMEOUT_SECS}s")
        return False
    try:
        cmd = (
            f"cd {GPU_REPO_PATH} && "
            "conda run -n autoresearch uv run train.py > run.log 2>&1"
        )
        result = subprocess.run(
            ["ssh", *_SSH_OPTS, GPU_BOX, cmd],
            capture_output=True, text=True, timeout=400,
        )
        return result.returncode == 0
    finally:
        _WIN_LM_STUDIO_SLOT.release()


def fetch_run_log() -> bool:
    """SCP run.log from the GPU runner back to Mac (read-only, no slot needed)."""
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
