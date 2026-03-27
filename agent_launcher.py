#!/usr/bin/env python3
"""
agent_launcher.py
-----------------
Hardware-aware agent launcher for the Perplexity-Tools orchestration stack.

Detects whether the remote Windows worker (Dell RTX 3080) is reachable and
routes the coder/heavy-reasoning role accordingly. Falls back gracefully to
Mac-only mode if the Windows node is offline.

Usage:
    python agent_launcher.py              # auto-detect with defaults
    python agent_launcher.py --configure  # interactive IP / hardware setup

References:
    hardware/SKILL.md     - hardware profiles and role matrix
    hardware/Modelfile.*  - Ollama model definitions
    config/routing.yml    - routing rules that consume the endpoints returned here
"""

import os
import sys
import json
import asyncio
import argparse
from pathlib import Path

try:
    import httpx
except ImportError:
    print("[agent_launcher] ERROR: httpx not installed. Run: pip install httpx")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Default hardware endpoints (from hardware/SKILL.md profiles)
# Override via environment variables or --configure flag
# ---------------------------------------------------------------------------

LOCAL_MAC_HOST    = os.getenv("LOCAL_MAC_HOST",    "127.0.0.1")
LOCAL_MAC_PORT    = int(os.getenv("LOCAL_MAC_PORT", "11434"))
LOCAL_MAC_URL     = f"http://{LOCAL_MAC_HOST}:{LOCAL_MAC_PORT}"
MAC_MANAGER_MODEL = os.getenv("MAC_MANAGER_MODEL", "qwen3:8b-instruct")

WINDOWS_IP        = os.getenv("WINDOWS_IP",   "192.168.1.100")
WINDOWS_PORT      = int(os.getenv("WINDOWS_PORT", "11434"))
REMOTE_WINDOWS_URL   = f"http://{WINDOWS_IP}:{WINDOWS_PORT}"
WINDOWS_CODER_MODEL  = os.getenv("WINDOWS_CODER_MODEL", "qwen3.5-35b-a3b-win")

# Timeout in seconds — short to avoid blocking the launcher when Windows is asleep
DETECT_TIMEOUT = int(os.getenv("AGENT_DETECT_TIMEOUT", "3"))

# State file for idempotency (Perplexity-Tools convention)
STATE_FILE = Path(".state/agents.json")


# ---------------------------------------------------------------------------
# Helper: check if a remote Ollama instance is reachable
# ---------------------------------------------------------------------------

async def check_remote_worker(base_url: str, timeout: int = DETECT_TIMEOUT) -> bool:
    """Return True if the Ollama instance at base_url is reachable."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{base_url}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Core: detect hardware and build routing state
# ---------------------------------------------------------------------------

async def initialize_environment() -> dict:
    """
    Detect available hardware and return agent routing state.

    Returns:
        dict with keys:
            manager_endpoint  - Ollama base URL for the manager/synthesis agent (Mac)
            coder_endpoint    - Ollama base URL for the coder/heavy-reasoning agent
            coder_model       - Model tag for the coder agent
            manager_model     - Model tag for the manager agent
            distributed       - True if Windows worker is reachable
            mac_only          - True if running in Mac-only degraded mode
    """
    mac_ok = await check_remote_worker(LOCAL_MAC_URL)
    win_ok = await check_remote_worker(REMOTE_WINDOWS_URL)

    if not mac_ok:
        print(f"[agent_launcher] WARNING: Local Mac Ollama not reachable at {LOCAL_MAC_URL}")
        print("  → Is Ollama running? Try: ollama serve")

    routing_state = {
        "manager_endpoint": LOCAL_MAC_URL,
        "manager_model":    MAC_MANAGER_MODEL,
        "coder_endpoint":   REMOTE_WINDOWS_URL if win_ok else LOCAL_MAC_URL,
        "coder_model":      WINDOWS_CODER_MODEL if win_ok else MAC_MANAGER_MODEL,
        "distributed":      win_ok,
        "mac_only":         not win_ok,
        "mac_reachable":    mac_ok,
        "windows_ip":       WINDOWS_IP,
    }

    return routing_state


# ---------------------------------------------------------------------------
# State persistence (idempotency: .state/agents.json)
# ---------------------------------------------------------------------------

def save_routing_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def load_routing_state() -> dict | None:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return None


# ---------------------------------------------------------------------------
# CLI interactive configuration
# ---------------------------------------------------------------------------

def interactive_configure() -> None:
    """Prompt user for hardware details and write to .env overrides."""
    print("\n=== Agent Launcher — Hardware Configuration ===")
    print("Press Enter to accept defaults shown in [brackets].\n")

    mac_host = input(f"  Mac Ollama host   [{LOCAL_MAC_HOST}]: ").strip() or LOCAL_MAC_HOST
    mac_port = input(f"  Mac Ollama port   [{LOCAL_MAC_PORT}]: ").strip() or str(LOCAL_MAC_PORT)
    win_ip   = input(f"  Windows IP        [{WINDOWS_IP}]: ").strip() or WINDOWS_IP
    win_port = input(f"  Windows port      [{WINDOWS_PORT}]: ").strip() or str(WINDOWS_PORT)

    env_path = Path(".env.local")
    lines = [
        f"LOCAL_MAC_HOST={mac_host}",
        f"LOCAL_MAC_PORT={mac_port}",
        f"WINDOWS_IP={win_ip}",
        f"WINDOWS_PORT={win_port}",
    ]
    env_path.write_text("\n".join(lines) + "\n")
    print(f"\n  Saved to {env_path}. Re-run without --configure to apply.\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main(args: argparse.Namespace) -> None:
    if args.configure:
        interactive_configure()
        return

    print("[agent_launcher] Detecting hardware...")
    state = await initialize_environment()

    # ── Print routing state ───────────────────────────────────────────────
    print("\n┌─ AGENT ROUTING STATE ─────────────────────────────────────────┐")
    mode = "DISTRIBUTED (Mac + Windows)" if state["distributed"] else "MAC-ONLY (degraded)"
    print(f"│  Mode        : {mode}")
    print(f"│  Manager     : {state['manager_endpoint']}  [{state['manager_model']}]")
    print(f"│  Coder       : {state['coder_endpoint']}  [{state['coder_model']}]")
    if state["mac_only"]:
        print("│  NOTE: Windows worker offline — all tasks routed to Mac")
    print("└" + "─" * 55)

    if state["distributed"]:
        proceed = input("\nProceed with distributed mode? [Y/n]: ").strip().lower()
        if proceed == "n":
            print("  To set up the Windows instance first, run: python setup_wizard.py")
            return
    else:
        print("\nWindows worker not detected. Running in Mac-only mode.")
        print("  To configure Windows: python agent_launcher.py --configure")
        print("  To install on Windows first: python setup_wizard.py")

    # Persist routing state for orchestrator consumers
    save_routing_state(state)
    print(f"\n[agent_launcher] Routing state saved to {STATE_FILE}")
    print("[agent_launcher] Ready. Import routing state in your orchestrator:")
    print("  from agent_launcher import initialize_environment")

    return state


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Hardware-aware agent launcher for Perplexity-Tools"
    )
    parser.add_argument(
        "--configure",
        action="store_true",
        help="Interactively configure hardware IP addresses and ports",
    )
    args = parser.parse_args()
    asyncio.run(main(args))
