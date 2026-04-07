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

# Mac LM Studio (separate from local Ollama — may be on a LAN IP)
MAC_LMS_HOST  = os.getenv("MAC_LMS_HOST",  "192.168.254.101")
MAC_LMS_PORT  = int(os.getenv("MAC_LMS_PORT", "1234"))
MAC_LMS_URL   = f"http://{MAC_LMS_HOST}:{MAC_LMS_PORT}"
MAC_LMS_MODEL = (os.getenv("MAC_LMS_MODEL")
                 or os.getenv("LMS_MAC_MODEL")
                 or "qwen3:8b-instruct")

WINDOWS_IP        = os.getenv("WINDOWS_IP",   "192.168.254.103")
WINDOWS_PORT      = int(os.getenv("WINDOWS_PORT", "11434"))
REMOTE_WINDOWS_URL   = f"http://{WINDOWS_IP}:{WINDOWS_PORT}"
WINDOWS_CODER_MODEL  = os.getenv("WINDOWS_CODER_MODEL", "qwen3.5-35b-a3b-win")

WINDOWS_LMS_PORT      = int(os.getenv("WINDOWS_LMS_PORT", "1234"))
REMOTE_WINDOWS_LMS_URL = f"http://{WINDOWS_IP}:{WINDOWS_LMS_PORT}"
LMS_API_TOKEN         = os.getenv("LM_STUDIO_API_TOKEN", "")
WINDOWS_LMS_MODEL     = (os.getenv("WINDOWS_LMS_MODEL")
                         or os.getenv("LMS_WIN_MODEL")
                         or "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2")

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


async def check_lmstudio_worker(base_url: str, timeout: int = DETECT_TIMEOUT) -> bool:
    """Reachability probe for Windows LM Studio (/v1/models).
    Passes LM_STUDIO_API_TOKEN as Bearer if set, so secured deployments are
    not misreported as unreachable. Timeout is honoured via AsyncClient.
    """
    url = f"{base_url.rstrip('/')}/v1/models"
    headers = {"Authorization": f"Bearer {LMS_API_TOKEN}"} if LMS_API_TOKEN else {}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers)
            return resp.status_code < 400
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
    mac_ok, mac_lms_ok, win_ok, lms_ok = await asyncio.gather(
        check_remote_worker(LOCAL_MAC_URL),
        check_lmstudio_worker(MAC_LMS_URL),
        check_remote_worker(REMOTE_WINDOWS_URL),
        check_lmstudio_worker(REMOTE_WINDOWS_LMS_URL),
    )

    mac_any = mac_ok or mac_lms_ok
    if not mac_any:
        print(f"[agent_launcher] WARNING: No Mac backend reachable "
              f"(Ollama={LOCAL_MAC_URL}, LMS={MAC_LMS_URL})")
        print("  → Start Ollama ('ollama serve') or LM Studio on the Mac")

    # Manager runs on Mac — prefer local Ollama, fall back to Mac LM Studio
    manager_endpoint = LOCAL_MAC_URL   if mac_ok     else MAC_LMS_URL
    manager_model    = MAC_MANAGER_MODEL if mac_ok   else MAC_LMS_MODEL
    manager_backend  = "mac-ollama"    if mac_ok     else "mac-lmstudio"

    routing_state = {
        "manager_endpoint":     manager_endpoint,
        "manager_model":        manager_model,
        "manager_backend":      manager_backend,
        "coder_endpoint":       (REMOTE_WINDOWS_URL      if win_ok
                                 else REMOTE_WINDOWS_LMS_URL if lms_ok
                                 else manager_endpoint),
        "coder_model":          (WINDOWS_CODER_MODEL     if win_ok
                                 else WINDOWS_LMS_MODEL       if lms_ok
                                 else manager_model),
        "coder_backend":        ("windows-ollama"    if win_ok
                                 else "windows-lmstudio" if lms_ok
                                 else "mac-degraded"),
        "mac_ollama_ok":        mac_ok,
        "mac_lmstudio_ok":      mac_lms_ok,
        "windows_ollama_ok":    win_ok,
        "windows_lm_studio_ok": lms_ok,
        "distributed":          win_ok or lms_ok,
        "mac_only":             not win_ok and not lms_ok,
        "mac_reachable":        mac_any,
        "windows_ip":           WINDOWS_IP,
        "lmstudio_endpoint":    REMOTE_WINDOWS_LMS_URL if lms_ok else None,
        "lmstudio_model":       WINDOWS_LMS_MODEL if lms_ok else None,
        "lmstudio_detected":    lms_ok,
        "mac_lmstudio_endpoint": MAC_LMS_URL if mac_lms_ok else None,
        "mac_lmstudio_model":    MAC_LMS_MODEL if mac_lms_ok else None,
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

    # --status: print saved state without re-probing
    if args.status:
        saved = load_routing_state()
        if saved is None:
            print("[agent_launcher] No state saved yet — run without --status first")
            sys.exit(1)
        print(json.dumps(saved, indent=2))
        return

    print("[agent_launcher] Detecting hardware...")
    state = await initialize_environment()

    # ── Print routing state ───────────────────────────────────────────────
    print("\n┌─ AGENT ROUTING STATE ─────────────────────────────────────────┐")
    mode = "DISTRIBUTED (Mac + Windows)" if state["distributed"] else "MAC-ONLY (degraded)"
    print(f"│  Mode        : {mode}")
    print(f"│  Manager     : {state['manager_endpoint']}  [{state['manager_model']}]")
    print(f"│  Coder       : {state['coder_endpoint']}  [{state['coder_model']}]  ({state['coder_backend']})")
    if state["mac_only"]:
        print("│  NOTE: Windows worker offline — all tasks routed to Mac")
    print("└" + "─" * 55)

    # Interactive prompt — skip in --write-state (non-interactive) mode
    if not args.write_state:
        if state["windows_ollama_ok"]:
            # Explicit confirmation only for primary Ollama path
            proceed = input("\nProceed with distributed mode? [Y/n]: ").strip().lower()
            if proceed == "n":
                print("  To set up the Windows instance first, run: python setup_wizard.py")
                return
        elif state["windows_lm_studio_ok"]:
            pass  # Silent fallback — LM Studio is the active coder backend
        else:
            print("\nWindows worker not detected. Running in Mac-only mode.")
            print("  To configure Windows: python agent_launcher.py --configure")
            print("  To install on Windows first: python setup_wizard.py")

    # Persist routing state for orchestrator consumers
    save_routing_state(state)

    if args.write_state:
        # Machine-readable one-liner for start.sh
        bk = state["coder_backend"]
        print(f"[agent_launcher] manager={state['manager_endpoint']}  "
              f"coder={state['coder_endpoint']} ({bk})  "
              f"distributed={state['distributed']}")
        return state

    print(f"\n[agent_launcher] Routing state saved to {STATE_FILE}")
    print("[agent_launcher] Ready. Import routing state in your orchestrator:")
    print("  from agent_launcher import initialize_environment")

    return state


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Hardware-aware agent launcher for Perplexity-Tools",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python agent_launcher.py                # detect + print + interactive\n"
            "  python agent_launcher.py --write-state  # detect, save, exit (non-interactive)\n"
            "  python agent_launcher.py --status       # print saved state, no probing\n"
            "  python agent_launcher.py --configure    # set hardware IPs interactively\n"
        ),
    )
    parser.add_argument(
        "--configure",
        action="store_true",
        help="Interactively configure hardware IP addresses and ports",
    )
    parser.add_argument(
        "--write-state",
        dest="write_state",
        action="store_true",
        help="Detect backends, write .state/agents.json, exit (non-interactive). "
             "Used by start.sh and automated callers.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print the last saved .state/agents.json without re-probing. "
             "Exits 1 if no state file exists yet.",
    )
    args = parser.parse_args()
    asyncio.run(main(args))
