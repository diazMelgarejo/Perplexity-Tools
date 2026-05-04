#!/usr/bin/env python3
"""
agent_launcher.py
-----------------
Hardware-aware agent launcher for the Perpetua-Tools orchestration stack.

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
import logging
import sys
import json
import asyncio
import argparse
import socket
from pathlib import Path
from urllib.parse import urlparse

from utils.hardware_policy import HardwareAffinityError, check_affinity

try:
    import httpx
except ImportError:
    print("[agent_launcher] ERROR: httpx not installed. Run: pip install httpx")
    sys.exit(1)

# Load .env files so vars are available whether called from start.sh or directly.
# .env.local overrides .env (machine-local settings take precedence).
try:
    from dotenv import load_dotenv as _load_dotenv
    _here = Path(__file__).parent
    _load_dotenv(_here / ".env",       override=False)
    _load_dotenv(_here / ".env.local", override=True)
except ImportError:
    pass  # python-dotenv not installed — rely on shell env vars


# ---------------------------------------------------------------------------
# Default hardware endpoints (from hardware/SKILL.md profiles)
# Override via environment variables or --configure flag
#
# Priority for each endpoint (highest → lowest):
#   1. Machine-local .env.local  (e.g. MAC_LMS_HOST, WINDOWS_IP)
#   2. Shared .env               (LM_STUDIO_MAC_ENDPOINT, LM_STUDIO_WIN_ENDPOINTS)
#   3. Shell environment vars    (exported by start.sh from network_autoconfig)
#   4. Hard-coded LAN defaults   (.110 = Mac LM Studio, .108 = Windows)
# ---------------------------------------------------------------------------

LOCAL_MAC_HOST    = os.getenv("LOCAL_MAC_HOST",    "127.0.0.1")
LOCAL_MAC_PORT    = int(os.getenv("LOCAL_MAC_PORT", "11434"))
LOCAL_MAC_URL     = f"http://{LOCAL_MAC_HOST}:{LOCAL_MAC_PORT}"
MAC_MANAGER_MODEL = os.getenv("MAC_MANAGER_MODEL", "glm-5.1:cloud")

# Mac LM Studio — parse LM_STUDIO_MAC_ENDPOINT if set (canonical form in .env),
# then fall back to explicit MAC_LMS_HOST/PORT vars, then hard-coded LAN default.
_mac_lms_ep = os.getenv("LM_STUDIO_MAC_ENDPOINT", "").strip()
if _mac_lms_ep:
    _p = urlparse(_mac_lms_ep)
    MAC_LMS_HOST = os.getenv("MAC_LMS_HOST", _p.hostname or "192.168.254.110")
    MAC_LMS_PORT = int(os.getenv("MAC_LMS_PORT", str(_p.port or 1234)))
else:
    MAC_LMS_HOST = os.getenv("MAC_LMS_HOST", "192.168.254.110")
    MAC_LMS_PORT = int(os.getenv("MAC_LMS_PORT", "1234"))
MAC_LMS_URL   = f"http://{MAC_LMS_HOST}:{MAC_LMS_PORT}"
MAC_LMS_MODEL = (os.getenv("MAC_LMS_MODEL")
                 or os.getenv("LMS_MAC_MODEL")
                 or "Qwen3.5-9B-MLX-4bit")

# Windows — WINDOWS_IP exported by start.sh; if absent parse LM_STUDIO_WIN_ENDPOINTS
# (first entry), then fall back to hard-coded LAN default.
_win_lms_eps = os.getenv("LM_STUDIO_WIN_ENDPOINTS", "").strip()
_win_lms_first = _win_lms_eps.split(",")[0].strip() if _win_lms_eps else ""
if not os.getenv("WINDOWS_IP") and _win_lms_first:
    _pw = urlparse(_win_lms_first)
    _win_ip_default = _pw.hostname or "192.168.254.108"
else:
    _win_ip_default = "192.168.254.108"

WINDOWS_IP        = os.getenv("WINDOWS_IP",   _win_ip_default)
WINDOWS_PORT      = int(os.getenv("WINDOWS_PORT", "11434"))
REMOTE_WINDOWS_URL   = f"http://{WINDOWS_IP}:{WINDOWS_PORT}"
WINDOWS_CODER_MODEL  = os.getenv(
    "WINDOWS_CODER_MODEL",
    "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2",  # verified Windows-only model
)

# ---------------------------------------------------------------------------
# Startup assertion — validate hardware policy on module load
# ---------------------------------------------------------------------------

_launcher_logger = logging.getLogger(__name__)


def _validate_hardware_policy(resolved_model: str) -> None:
    """Raise HardwareAffinityError if resolved_model is not valid for Windows execution."""
    try:
        from utils.hardware_policy import load_policy
        policy = load_policy()
        valid_for_windows = {
            m.lower()
            for m in (policy.get("windows_only", []) or []) + (policy.get("shared", []) or [])
        }
        if valid_for_windows and resolved_model.lower() not in valid_for_windows:
            _launcher_logger.critical(
                "Hardware Policy Violation: Resolved model '%s' is not validated "
                "for Windows execution. Halting orchestration.",
                resolved_model,
            )
            raise HardwareAffinityError(f"Invalid model affinity: {resolved_model}")
    except HardwareAffinityError:
        raise
    except Exception as _e:
        _launcher_logger.warning("Hardware policy startup validation skipped: %s", _e)


_validate_hardware_policy(WINDOWS_CODER_MODEL)

WINDOWS_LMS_PORT      = int(os.getenv("WINDOWS_LMS_PORT", "1234"))
REMOTE_WINDOWS_LMS_URL = f"http://{WINDOWS_IP}:{WINDOWS_LMS_PORT}"
LMS_API_TOKEN         = os.getenv("LM_STUDIO_API_TOKEN", "")
WINDOWS_LMS_MODEL     = (os.getenv("WINDOWS_LMS_MODEL")
                         or os.getenv("LMS_WIN_MODEL")
                         or "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2")

# Timeout in seconds — short to avoid blocking the launcher when Windows is asleep
DETECT_TIMEOUT = int(os.getenv("AGENT_DETECT_TIMEOUT", "3"))

# State file for routing state (separate from AgentTracker's agents.json)
STATE_FILE = Path(".state/routing.json")


# ---------------------------------------------------------------------------
# Device identity — detect when two URLs point to the same physical machine
# ---------------------------------------------------------------------------

def _get_local_ips() -> frozenset[str]:
    """Return all IPv4 addresses that belong to this machine.

    Uses three strategies (all non-blocking):
    1. Resolve the machine's hostname.
    2. UDP routing trick — open a socket toward a routable IP; the OS fills in
       the outbound LAN IP without actually sending any packets.
    3. Always include the loopback aliases.
    """
    local: set[str] = {"127.0.0.1", "0.0.0.0", "localhost"}
    try:
        local.add(socket.gethostbyname(socket.gethostname()))
    except OSError:
        pass
    for probe in ("8.8.8.8", "192.168.0.1", "10.0.0.1"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(0.2)
                s.connect((probe, 80))
                local.add(s.getsockname()[0])
                break
        except OSError:
            pass
    return frozenset(local)


def _host_of(url: str) -> str:
    """Extract hostname from a URL, normalising loopback aliases to 127.0.0.1."""
    h = urlparse(url).hostname or url
    return "127.0.0.1" if h in ("localhost", "::1") else h


def _is_local_endpoint(url: str, local_ips: frozenset[str]) -> bool:
    """Return True if *url* points to this machine."""
    return _host_of(url) in local_ips


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
# Helpers: logging, model discovery, missing-backend prompt, routing builder
# ---------------------------------------------------------------------------

def _log_backend(label: str, ok: bool, url: str) -> None:
    status = "✓" if ok else "✗"
    print(f"[agent_launcher]   {status}  {label:<18} {url}")


async def _fetch_models(
    mac_ok: bool,
    mac_url: str,
    mac_lms_ok: bool,
    lms_url: str,
) -> dict[str, list[str]]:
    """Query live local backends for their actual loaded model names.

    Runs while LAN probes are still in flight — adds no extra latency.
    Falls back to an empty list on any error; callers use env-var constants.
    """
    async def _ollama_tags(url: str) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=DETECT_TIMEOUT) as c:
                r = await c.get(f"{url}/api/tags")
                return [m["name"] for m in r.json().get("models", [])]
        except Exception:
            return []

    async def _lms_models(url: str) -> list[str]:
        hdrs = {"Authorization": f"Bearer {LMS_API_TOKEN}"} if LMS_API_TOKEN else {}
        try:
            async with httpx.AsyncClient(timeout=DETECT_TIMEOUT) as c:
                r = await c.get(f"{url.rstrip('/')}/v1/models", headers=hdrs)
                return [m["id"] for m in r.json().get("data", [])]
        except Exception:
            return []

    coros: dict[str, object] = {}
    if mac_ok:
        coros["mac-ollama"] = _ollama_tags(mac_url)
    if mac_lms_ok:
        coros["mac-lmstudio"] = _lms_models(lms_url)
    if not coros:
        return {}
    gathered = await asyncio.gather(*coros.values(), return_exceptions=True)
    return {
        key: val if isinstance(val, list) else []
        for key, val in zip(coros.keys(), gathered)
    }


def _prompt_missing(items: list[str]) -> None:
    """Print a diagnostic table and ask the user whether to continue offline.

    Non-interactive (stdin not a tty): warns and returns to continue.
    Interactive: calls sys.exit(1) if the user declines.
    """
    print("\n" + "─" * 64)
    print("  SETUP INCOMPLETE — could not reach:")
    for item in items:
        print(f"    ✗  {item}")
    print("─" * 64)
    if not sys.stdin.isatty():
        print("  [non-interactive] continuing offline — fix backends and restart")
        return
    ans = input("  Continue offline anyway? [y/N]: ").strip().lower()
    if ans != "y":
        sys.exit(1)


def _build_routing_state(
    mac_ok: bool,
    mac_lms_ok: bool,
    win_ok: bool,
    lms_ok: bool,
    local_models: dict[str, list[str]],
    mac_lms_is_local: bool,
    local_ips: frozenset[str],
) -> dict:
    """Construct the routing state dict.

    Agent assignment happens here — only after hardware is confirmed and
    actual model names have been queried from live backends.
    """
    def _first(key: str, fallback: str) -> str:
        models = local_models.get(key, [])
        return models[0] if models else fallback

    # Manager: Mac Ollama first, then Mac LM Studio
    if mac_ok:
        manager_endpoint = LOCAL_MAC_URL
        manager_model    = _first("mac-ollama", MAC_MANAGER_MODEL)
        manager_backend  = "mac-ollama"
    else:
        manager_endpoint = MAC_LMS_URL
        manager_model    = _first("mac-lmstudio", MAC_LMS_MODEL)
        manager_backend  = "mac-lmstudio"

    mac_any = mac_ok or mac_lms_ok

    try:
        check_affinity(manager_model, "mac")
    except HardwareAffinityError as exc:
        print(f"[agent_launcher] ✗  {exc}")
        mac_ok = False
        mac_lms_ok = False
        mac_any = False

    coder_endpoint = (REMOTE_WINDOWS_LMS_URL if lms_ok
                      else REMOTE_WINDOWS_URL if win_ok
                      else manager_endpoint)
    coder_model = (WINDOWS_LMS_MODEL if lms_ok
                   else WINDOWS_CODER_MODEL if win_ok
                   else manager_model)
    coder_backend = ("windows-lmstudio" if lms_ok
                     else "windows-ollama" if win_ok
                     else "mac-degraded")
    coder_platform = "win" if coder_backend.startswith("windows-") else "mac"

    try:
        check_affinity(coder_model, coder_platform)
    except HardwareAffinityError as exc:
        print(f"[agent_launcher] ✗  {exc}")
        print("[agent_launcher]   affinity violation escalates to controller; refusing silent fallback")
        raise

    return {
        "manager_endpoint":      manager_endpoint,
        "manager_model":         manager_model,
        "manager_backend":       manager_backend,
        "coder_endpoint":        coder_endpoint,
        "coder_model":           coder_model,
        "coder_backend":         coder_backend,
        "mac_ollama_ok":         mac_ok,
        "mac_lmstudio_ok":       mac_lms_ok,
        "windows_ollama_ok":     win_ok,
        "windows_lm_studio_ok":  lms_ok,
        "distributed":           win_ok or lms_ok,
        "mac_only":              not win_ok and not lms_ok,
        "mac_reachable":         mac_any,
        "windows_ip":            WINDOWS_IP,
        "lmstudio_endpoint":     REMOTE_WINDOWS_LMS_URL if lms_ok else None,
        "lmstudio_model":        WINDOWS_LMS_MODEL if lms_ok else None,
        "lmstudio_detected":     lms_ok,
        "mac_lmstudio_endpoint": MAC_LMS_URL if mac_lms_ok else None,
        "mac_lmstudio_model":    MAC_LMS_MODEL if mac_lms_ok else None,
        "mac_lmstudio_is_local": mac_lms_is_local,
        "local_ips":             sorted(local_ips),
        "discovered_models":     local_models,
    }


# ---------------------------------------------------------------------------
# Core: detect hardware and build routing state
# ---------------------------------------------------------------------------

async def initialize_environment() -> dict:
    """Detect available hardware and return agent routing state.

    All four backend probes fire concurrently at t=0. Local (Mac) results are
    awaited first and gate agent-role commitment. LAN results (Win LM Studio is
    always online) are collected as soon as they arrive — no sequential blocking.

    Returns a dict suitable for writing to .state/routing.json.
    """
    # ── All probes start at t=0 ───────────────────────────────────────────
    t_mac_ol  = asyncio.create_task(check_remote_worker(LOCAL_MAC_URL),            name="mac-ollama")
    t_mac_lms = asyncio.create_task(check_lmstudio_worker(MAC_LMS_URL),            name="mac-lmstudio")
    t_win_ol  = asyncio.create_task(check_remote_worker(REMOTE_WINDOWS_URL),       name="win-ollama")
    t_win_lms = asyncio.create_task(check_lmstudio_worker(REMOTE_WINDOWS_LMS_URL), name="win-lmstudio")

    # ── Step 1: await local results — they gate agent-role commitment ─────
    print("[agent_launcher] Probing backends…")
    mac_ok, mac_lms_ok = await asyncio.gather(t_mac_ol, t_mac_lms)
    _log_backend("Mac Ollama",    mac_ok,    LOCAL_MAC_URL)
    _log_backend("Mac LM Studio", mac_lms_ok, MAC_LMS_URL)

    # ── Step 2: identify actual models on live local backends ─────────────
    # Runs while LAN tasks are still in flight — no extra wall-clock cost.
    local_models = await _fetch_models(mac_ok, LOCAL_MAC_URL, mac_lms_ok, MAC_LMS_URL)
    for backend, models in local_models.items():
        if models:
            preview = ", ".join(models[:3]) + (" …" if len(models) > 3 else "")
            print(f"[agent_launcher]   ↳ {backend}: {preview}")

    # ── Step 3: collect LAN results (Win LM Studio usually already done) ──
    win_ok, lms_ok = await asyncio.gather(t_win_ol, t_win_lms)
    _log_backend("Win Ollama",    win_ok, REMOTE_WINDOWS_URL)
    _log_backend("Win LM Studio", lms_ok, REMOTE_WINDOWS_LMS_URL)

    # ── Step 4: device-identity guard ────────────────────────────────────
    # If a "remote" URL resolves to a local IP, the user mis-configured
    # WINDOWS_IP — do NOT spawn a second researcher on the same device.
    local_ips = _get_local_ips()

    if win_ok and _is_local_endpoint(REMOTE_WINDOWS_URL, local_ips):
        print(f"[agent_launcher] ⚠  Windows Ollama {REMOTE_WINDOWS_URL} is THIS device"
              f" — ignoring (one role per device; local IPs: {sorted(local_ips)})")
        win_ok = False

    if lms_ok and _is_local_endpoint(REMOTE_WINDOWS_LMS_URL, local_ips):
        print(f"[agent_launcher] ⚠  Windows LM Studio {REMOTE_WINDOWS_LMS_URL} is THIS device"
              f" — ignoring (one role per device)")
        lms_ok = False

    # If Mac Ollama AND Mac LM Studio are both on this device, Ollama takes
    # priority (avoid two simultaneous inference loads on the same GPU/CPU).
    mac_lms_is_local = _is_local_endpoint(MAC_LMS_URL, local_ips)
    if mac_lms_is_local and mac_ok and mac_lms_ok:
        print(f"[agent_launcher] ℹ  Mac LM Studio ({MAC_LMS_URL}) is on this device"
              f" — Ollama takes precedence (one role per device)")
        mac_lms_ok = False

    # ── Step 5: prompt if no local backend found ──────────────────────────
    mac_any = mac_ok or mac_lms_ok
    if not mac_any:
        _prompt_missing([
            f"Mac Ollama      → {LOCAL_MAC_URL}  (run: ollama serve)",
            f"Mac LM Studio   → {MAC_LMS_URL}  (start LM Studio server)",
        ])

    # ── Step 6: assign agents — hardware confirmed, models identified ─────
    return _build_routing_state(
        mac_ok, mac_lms_ok, win_ok, lms_ok, local_models, mac_lms_is_local, local_ips
    )


# ---------------------------------------------------------------------------
# Auto-write detected IPs back to .env so future runs are pre-configured
# ---------------------------------------------------------------------------

def _persist_detected_ips(state: dict) -> None:
    """Write confirmed live endpoints back into .env so the next run is pre-configured.

    Only updates lines that already exist in the file (safe, non-destructive).
    Skips writing if both endpoints are already correct to keep the file stable.
    """
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return

    mac_lms_url = state.get("mac_lmstudio_endpoint") or MAC_LMS_URL
    win_lms_url = state.get("lmstudio_endpoint") or REMOTE_WINDOWS_LMS_URL

    try:
        lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError:
        return

    updated = False
    new_lines = []
    for line in lines:
        stripped = line.rstrip("\n").rstrip()
        if stripped.startswith("LM_STUDIO_MAC_ENDPOINT="):
            want = f"LM_STUDIO_MAC_ENDPOINT={mac_lms_url}\n"
            if line != want:
                line = want
                updated = True
        elif stripped.startswith("LM_STUDIO_WIN_ENDPOINTS="):
            # Preserve comma-separated extras; replace first entry only
            rest = stripped[len("LM_STUDIO_WIN_ENDPOINTS="):]
            parts = [p.strip() for p in rest.split(",")]
            if parts[0] != win_lms_url:
                parts[0] = win_lms_url
                want = "LM_STUDIO_WIN_ENDPOINTS=" + ",".join(parts) + "\n"
                line = want
                updated = True
        elif stripped.startswith("WINDOWS_IP="):
            want = f"WINDOWS_IP={WINDOWS_IP}\n"
            if line != want:
                line = want
                updated = True
        new_lines.append(line)

    if updated:
        try:
            env_path.write_text("".join(new_lines), encoding="utf-8")
            print(f"[agent_launcher] ✎  .env updated with live endpoints"
                  f" (Mac LMS: {mac_lms_url}  Win LMS: {win_lms_url})")
        except OSError as e:
            print(f"[agent_launcher] ⚠  could not write .env: {e}")
    else:
        print(f"[agent_launcher] ✔  .env already has correct endpoints — no update needed")


# ---------------------------------------------------------------------------
# State persistence (idempotency: .state/routing.json)
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
            # Explicit confirmation only when primary Win Ollama path is active
            proceed = input("\nProceed with distributed mode? [Y/n]: ").strip().lower()
            if proceed == "n":
                print("  To set up the Windows instance first, run: python setup_wizard.py")
                return
        elif state["windows_lm_studio_ok"]:
            pass  # LM Studio is the active coder backend — no prompt needed
        elif state["mac_reachable"]:
            print("\nWindows worker not detected. Running in Mac-only mode.")
            print("  To configure Windows: python agent_launcher.py --configure")
            print("  To install on Windows first: python setup_wizard.py")

    # Persist routing state for orchestrator consumers
    save_routing_state(state)
    # Write confirmed live endpoints back to .env so future runs start correctly
    _persist_detected_ips(state)

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
        description="Hardware-aware agent launcher for Perpetua-Tools",
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
        help="Detect backends, write .state/routing.json, exit (non-interactive). "
             "Used by start.sh and automated callers.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print the last saved .state/routing.json without re-probing. "
             "Exits 1 if no state file exists yet.",
    )
    args = parser.parse_args()
    asyncio.run(main(args))
