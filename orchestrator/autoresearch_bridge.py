"""orchestrator/autoresearch_bridge.py

Layer 4 integration: karpathy/autoresearch as a managed foot-soldier.

Responsibilities
----------------
- Idempotent git sync of the canonical autoresearch clone on the Windows GPU runner.
- Spawning the three cognitive swarm agents (Coder, Evaluator, Orchestrator) via
  the top-level Perplexity-Tools AgentTracker so lifecycle and idempotency are
  consistent with the rest of the stack.
- Reading swarm_state.md for GPU lock status before dispatching any training run.

Design rules (from approved interoperability contract)
------------------------------------------------------
1. ONLY Perplexity-Tools/orchestrator.py (or the FastAPI /autoresearch/* endpoints)
   may call sync_autoresearch_idempotent().  Layers 2-4 treat autoresearch as
   read-only from a lifecycle perspective.
2. The autoresearch clone lives in ONE canonical path on the Windows GPU runner:
       C:/Users/<WINUSER>/cogntiv/autoresearch/
   Never duplicate it.
3. File transfer uses scp only (rsync not guaranteed on Windows SSH sessions).
4. API keys are NEVER written to files; they are injected as session env vars.
5. GPU lock is the IDLE/BUSY flag in swarm_state.md — no external queue daemon.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── configuration (resolved from environment, never hard-coded secrets) ────────

GPU_BOX: str = os.environ.get("GPU_BOX", "WINUSER@192.168.1.100")
GPU_REPO_PATH: str = os.environ.get("GPU_REPO_PATH", "cogntiv/autoresearch")
AUTORESEARCH_REMOTE: str = "https://github.com/karpathy/autoresearch.git"
SSH_TIMEOUT: int = int(os.environ.get("SSH_TIMEOUT", "90"))

# SSH identity key — set DELL_SSH_KEY in .env.local (session-only, gitignored).
# Falls back to the default SSH agent / ~/.ssh/config if unset.
_SSH_KEY: str = os.environ.get("DELL_SSH_KEY", "")
_SSH_OPTS: list[str] = (
    ["-i", _SSH_KEY, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
    if _SSH_KEY else
    ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
)

# Local Mac path — used only for git history, SKILL.md edits, swarm_state.md.
LOCAL_REPO_PATH: Path = Path(
    os.environ.get("LOCAL_AUTORESEARCH_PATH", str(Path.home() / "cogntiv" / "autoresearch"))
)
SWARM_STATE_FILE: Path = LOCAL_REPO_PATH / "swarm_state.md"


# ── data types ────────────────────────────────────────────────────────────────

@dataclass
class SyncResult:
    ok: bool
    sha: str = ""
    error: str = ""


@dataclass
class SwarmState:
    gpu_status: str = "IDLE"       # IDLE | BUSY
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
    """
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
            return SyncResult(ok=False, error=result.stderr.strip())
        sha = result.stdout.strip().splitlines()[-1]  # last line = HEAD sha
        return SyncResult(ok=True, sha=sha)
    except subprocess.TimeoutExpired:
        return SyncResult(ok=False, error=f"SSH timeout after {SSH_TIMEOUT}s")
    except Exception as exc:  # noqa: BLE001
        return SyncResult(ok=False, error=str(exc))


# ── bootstrap: ensure the repo exists on the GPU runner (first-run only) ──────

def bootstrap_autoresearch_on_runner() -> SyncResult:
    """Clone autoresearch on the Windows GPU runner if it does not exist yet.

    Idempotent: if the directory already exists, falls through to a normal sync.
    """
    check_cmd = f"if not exist {GPU_REPO_PATH} git clone {AUTORESEARCH_REMOTE} {GPU_REPO_PATH}"
    try:
        subprocess.run(
            ["ssh", *_SSH_OPTS, GPU_BOX, check_cmd],
            capture_output=True,
            text=True,
            timeout=SSH_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001
        return SyncResult(ok=False, error=f"Bootstrap failed: {exc}")
    return sync_autoresearch_idempotent()


# ── GPU lock helpers (read/write swarm_state.md on Mac) ───────────────────────

def read_swarm_state() -> SwarmState:
    """Parse swarm_state.md into a SwarmState dataclass.

    Returns a default IDLE state if the file does not exist yet.
    """
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
    """Return True if swarm_state.md reports GPU: IDLE."""
    return read_swarm_state().gpu_status.upper() == "IDLE"


# ── deploy train.py to runner ─────────────────────────────────────────────────

def deploy_train_py() -> bool:
    """Copy the locally edited train.py to the Windows GPU runner via scp.

    Called by the Coder agent after every edit, before dispatching a run.
    Returns True on success.
    """
    local_train = LOCAL_REPO_PATH / "train.py"
    if not local_train.exists():
        return False
    result = subprocess.run(
        ["scp", *_SSH_OPTS, str(local_train), f"{GPU_BOX}:{GPU_REPO_PATH}/train.py"],
        capture_output=True,
        text=True,
        timeout=SSH_TIMEOUT,
    )
    return result.returncode == 0


# ── dispatch training run on GPU runner ───────────────────────────────────────

def run_experiment_on_gpu() -> bool:
    """SSH into Windows runner and execute train.py inside the cogntiv312 conda env.

    Uses CMD syntax over SSH (Windows default shell).
    stdout/stderr are redirected to run.log on the runner.
    Returns True if the SSH call itself succeeded (not whether val_bpb improved).
    """
    cmd = (
        f"cd {GPU_REPO_PATH} && "
        "conda run -n cogntiv312 uv run train.py > run.log 2>&1"
    )
    result = subprocess.run(
        ["ssh", *_SSH_OPTS, GPU_BOX, cmd],
        capture_output=True,
        text=True,
        timeout=400,  # 5 min budget + startup headroom
    )
    return result.returncode == 0


# ── fetch run.log back to Mac ─────────────────────────────────────────────────

def fetch_run_log() -> bool:
    """Copy run.log from the Windows runner to the local Mac repo dir via scp.

    Called by the Coder agent after run_experiment_on_gpu() completes.
    The Evaluator agent then reads the local log.txt.
    """
    result = subprocess.run(
        [
            "scp", *_SSH_OPTS,
            f"{GPU_BOX}:{GPU_REPO_PATH}/run.log",
            str(LOCAL_REPO_PATH / "log.txt"),
        ],
        capture_output=True,
        text=True,
        timeout=SSH_TIMEOUT,
    )
    return result.returncode == 0


# ── swarm_state.md initialiser ────────────────────────────────────────────────

def init_swarm_state(run_tag: str) -> None:
    """Write a fresh swarm_state.md into the local autoresearch repo.

    Called once by the orchestrator when a new autoresearch session starts.
    run_tag matches the autoresearch branch name convention (e.g. 'mar22').
    """
    content = textwrap.dedent(f"""\
        # Swarm State — {run_tag}
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
        <!-- Only the Coder agent may flip IDLE → BUSY and back. -->
    """)
    SWARM_STATE_FILE.write_text(content, encoding="utf-8")


# ── convenience: full pre-run checklist ───────────────────────────────────────

def preflight(run_tag: Optional[str] = None) -> dict:
    """Run the full pre-flight sequence before starting an autoresearch session.

    Steps (all idempotent):
    1. Bootstrap / sync autoresearch on GPU runner.
    2. Initialise swarm_state.md on Mac (only if run_tag supplied and file absent).

    Returns a dict with keys: sync_ok, sha, swarm_state_initialised.
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
