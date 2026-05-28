#!/usr/bin/env python3
"""
orchestrator/lan_discovery.py
-----------------------------
LAN-wide AI model discovery and orchestration takeover system.

Scans the local network for running AI inference servers (Ollama, LM Studio, MLX)
and presents a user-consent UI for selective or full takeover by Perpetua-Tools.

Based on distributed AI orchestration patterns:
- Service registration & discovery (IETF draft-yang-dmsc)
- Automatic peer discovery (exo-explore/exo)
- Resource pool quorum (Microsoft SCOM patterns)

Usage:
  python -m orchestrator.lan_discovery --scan
  python -m orchestrator.lan_discovery --scan --subnet 192.168.1.0/24
  python -m orchestrator.lan_discovery --interactive  # consent UI
"""

import os
import sys
import json
import asyncio
import ipaddress
import logging
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

try:
    import httpx
except ImportError:
    httpx = None

# Common AI inference server ports
DEFAULT_PORTS = [
    11434,  # Ollama
    1234,   # LM Studio
    8080,   # Generic ML serve
    5000,   # Flask/custom
]

# Discovery timeout per host
PROBE_TIMEOUT = 2  # seconds

# State file
DISCOVERY_STATE_FILE = Path(".state/lan_discovery.json")
log = logging.getLogger("orchestrator.lan_discovery")


def _utc_now_iso() -> str:
    """Return an ISO 8601 timestamp with an explicit UTC offset."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AIEndpoint:
    """Discovered AI inference endpoint."""
    host: str
    port: int
    server_type: str  # "ollama", "lm_studio", "mlx", "unknown"
    models: List[str]
    version: Optional[str] = None
    hardware_info: Optional[Dict] = None
    last_seen: str = ""
    takeover_consented: bool = False

    def __post_init__(self):
        if not self.last_seen:
            self.last_seen = _utc_now_iso()

    @property
    def endpoint_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def to_dict(self) -> dict:
        return asdict(self)


class LANDiscovery:
    """
    LAN-wide AI endpoint discovery and orchestration manager.
    """

    def __init__(self, subnet: str = None, ports: List[int] = None):
        """
        Args:
            subnet: CIDR notation (e.g., "192.168.1.0/24"). Auto-detects if None.
            ports: List of ports to scan. Uses DEFAULT_PORTS if None.
        """
        self.subnet = subnet or self._detect_local_subnet()
        self.ports = ports or DEFAULT_PORTS
        self.discovered: List[AIEndpoint] = []

    def _detect_local_subnet(self) -> str:
        """
        Auto-detect local subnet from machine's network interface.
        Fallback to 192.168.1.0/24 if detection fails.
        """
        try:
            import socket
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            # Assume /24 subnet
            parts = local_ip.split(".")
            subnet = f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"
            return subnet
        except Exception as exc:
            log.warning(
                "Failed to auto-detect local subnet (%s); falling back to 192.168.1.0/24",
                exc,
            )
            return "192.168.1.0/24"  # Safe default

    async def _probe_endpoint(self, host: str, port: int) -> Optional[AIEndpoint]:
        """
        Probe a single host:port for AI inference server.
        Returns AIEndpoint if found, None otherwise.
        """
        if httpx is None:
            raise RuntimeError("httpx not installed. Run: pip install httpx")

        base_url = f"http://{host}:{port}"
        
        try:
            async with httpx.AsyncClient(timeout=PROBE_TIMEOUT) as client:
                # Try Ollama API
                resp = await client.get(f"{base_url}/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    models = [m["name"] for m in data.get("models", [])]
                    return AIEndpoint(
                        host=host,
                        port=port,
                        server_type="ollama",
                        models=models,
                        version=data.get("version"),
                    )
                
                # Try LM Studio API (v1/models endpoint)
                resp = await client.get(f"{base_url}/v1/models")
                if resp.status_code == 200:
                    data = resp.json()
                    models = [m["id"] for m in data.get("data", [])]
                    return AIEndpoint(
                        host=host,
                        port=port,
                        server_type="lm_studio",
                        models=models,
                    )
                
                # Try generic health check
                for endpoint in ["/health", "/api/health", "/v1/health"]:
                    try:
                        resp = await client.get(f"{base_url}{endpoint}")
                        if resp.status_code == 200:
                            return AIEndpoint(
                                host=host,
                                port=port,
                                server_type="unknown",
                                models=[],
                            )
                    except Exception as exc:
                        log.debug("Health probe failed for %s%s: %s", base_url, endpoint, exc)
                        continue
        
        except Exception as exc:
            log.debug("Endpoint probe failed for %s: %s", base_url, exc)
            return None
        
        return None

    async def scan_lan(self) -> List[AIEndpoint]:
        """
        Scan the entire subnet for AI inference servers.
        Returns list of discovered AIEndpoint objects.
        """
        print(f"[lan_discovery] Scanning subnet {self.subnet} on ports {self.ports}...")
        
        network = ipaddress.ip_network(self.subnet, strict=False)
        tasks = []
        
        for ip in network.hosts():
            for port in self.ports:
                task = self._probe_endpoint(str(ip), port)
                tasks.append(task)
        
        # Run all probes concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out None and exceptions
        self.discovered = [r for r in results if isinstance(r, AIEndpoint)]
        
        print(f"[lan_discovery] Found {len(self.discovered)} AI endpoints")
        return self.discovered

    def save_discovery_state(self) -> None:
        """Persist discovered endpoints to state file."""
        DISCOVERY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "discovered_at": _utc_now_iso(),
            "subnet": self.subnet,
            "endpoints": [ep.to_dict() for ep in self.discovered],
        }
        with open(DISCOVERY_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
        print(f"[lan_discovery] State saved to {DISCOVERY_STATE_FILE}")

    def load_discovery_state(self) -> Optional[Dict]:
        """Load previously discovered endpoints."""
        if DISCOVERY_STATE_FILE.exists():
            with open(DISCOVERY_STATE_FILE) as f:
                return json.load(f)
        return None

    def print_discovery_table(self) -> None:
        """
        Print discovered endpoints in a formatted table.
        """
        if not self.discovered:
            print("\nNo AI endpoints discovered.\n")
            return
        
        print("\n" + "=" * 100)
        print("DISCOVERED AI INFERENCE SERVERS")
        print("=" * 100)
        print(f"{'#':<4} {'Host':<16} {'Port':<7} {'Type':<12} {'Models':<40} {'Consent'}")
        print("-" * 100)
        
        for idx, ep in enumerate(self.discovered, 1):
            models_str = ", ".join(ep.models[:3]) if ep.models else "(none)"
            if len(ep.models) > 3:
                models_str += f" +{len(ep.models) - 3} more"
            consent_mark = "✓ YES" if ep.takeover_consented else "○ NO"
            print(f"{idx:<4} {ep.host:<16} {ep.port:<7} {ep.server_type:<12} {models_str:<40} {consent_mark}")
        
        print("=" * 100 + "\n")

    def interactive_consent(self) -> List[AIEndpoint]:
        """
        Interactive user consent UI for endpoint takeover.
        Returns list of endpoints user consented to.
        """
        if not self.discovered:
            print("No endpoints to consent. Run --scan first.")
            return []
        
        self.print_discovery_table()
        
        print("\nPerpetua-Tools can take over these AI endpoints for distributed orchestration.")
        print("You can:")
        print("  - Select specific endpoints by number (e.g., '1,3,5')")
        print("  - Take over ALL endpoints by typing 'all'")
        print("  - Skip takeover by typing 'none' or pressing Enter\n")
        
        choice = input("Your choice: ").strip().lower()
        
        consented = []
        
        if choice == "all":
            for ep in self.discovered:
                ep.takeover_consented = True
                consented.append(ep)
            print(f"\n✓ User consented to take over ALL {len(consented)} endpoints.")
        
        elif choice and choice != "none":
            try:
                indices = [int(x.strip()) for x in choice.split(",")]
                for idx in indices:
                    if 1 <= idx <= len(self.discovered):
                        ep = self.discovered[idx - 1]
                        ep.takeover_consented = True
                        consented.append(ep)
                print(f"\n✓ User consented to take over {len(consented)} endpoint(s).")
            except ValueError:
                print("\n✗ Invalid input. No endpoints selected.")
        
        else:
            print("\n○ No takeover. Exiting.")
        
        return consented


def _host_from_endpoint(value: str) -> str:
    """Extract a bare IPv4/hostname from an env URL or host:port string."""
    raw = (value or "").strip()
    if not raw:
        return ""
    if "://" in raw:
        raw = raw.split("://", 1)[1]
    return raw.split(":")[0].strip()


def pick_windows_lmstudio_host(
    hosts: list[str],
    *,
    local_ip: str,
    preferred_win_ip: str = "",
) -> str | None:
    """Choose the Windows LM Studio host from a LAN scan.

    Mac LM Studio is a mirror on the same port (1234). A naive scan-order pick
    often selects the Mac (.105) before the Win GPU (.108), breaking dispatch.
    """
    if not hosts:
        return None

    seen: set[str] = set()
    candidates: list[str] = []
    for host in hosts:
        if host and host not in seen:
            seen.add(host)
            candidates.append(host)

    for hint in (preferred_win_ip, os.environ.get("WIN_IP", "")):
        host = _host_from_endpoint(hint)
        if host and host in candidates:
            return host

    non_local = [
        host
        for host in candidates
        if host != local_ip and not host.startswith("127.")
    ]
    if len(non_local) == 1:
        return non_local[0]
    if non_local:
        for host in non_local:
            if host.endswith(".108"):
                return host
        return non_local[-1]

    return candidates[0]


def detect_active_tilting_ip() -> str:
    """Derive the Windows GPU endpoint base URL from the local subnet at runtime.

    Implements the v0.9.9.5 Active Tilting spec: Option B (Discovered IPs).
    Uses NetworkAutoConfig.get_working_local_ip() and full Win probe with a
    25-second timeout threshold to prevent hanging the startup sequence.

    Priority order (mirrors LAN_GPU_IP_OVERRIDE from the hardware matrix):
      1. LAN_GPU_IP_OVERRIDE env var — absolute override, any subnet
      2. LM_STUDIO_WIN_ENDPOINTS env var — backward-compat with existing .env files
      3. UDP routing trick (no packets sent) — Live probe of outbound interface via NetworkAutoConfig (Option B)
      4. Hardcoded 192.168.254.108 (fallback)
    """
    for env_var in ("LAN_GPU_IP_OVERRIDE", "LM_STUDIO_WIN_ENDPOINTS"):
        val = os.environ.get(env_var, "")
        if val:
            return val if val.startswith("http") else f"http://{val}"
    try:
        from packages.net_utils.network_autoconfig import NetworkAutoConfig
        import threading
        
        result = [None]
        
        def do_discovery():
            """
            Attempts to discover a local LM Studio host and return its base HTTP URL, falling back to a subnet-derived Windows endpoint if none are found.
            
            Uses NetworkAutoConfig to determine the working local IP, probes the local /24 prefix for services labeled "lmstudio", and if any host is discovered returns "http://{host}". If no hosts are found, returns "http://{subnet}.108" where {subnet} is the first three octets of the working local IP.
            
            Returns:
                str: Base HTTP URL of the discovered LM Studio host or the subnet fallback (e.g., "http://192.168.1.108").
            """
            configurer = NetworkAutoConfig()
            local_ip = configurer.get_working_local_ip()
            subnet = ".".join(local_ip.split(".")[:3])
            
            # scan_timeout of 0.08s * 254 IPs = ~20.3 seconds max, safely under 25s thread budget
            found = configurer.discover_lan_agents(subnet_prefix=subnet, services=["lmstudio"], scan_timeout=0.08)
            lm_hosts = found.get("lmstudio") if found else []
            if lm_hosts:
                preferred = configurer.preferred_ips.get("Windows", "")
                win_ip = pick_windows_lmstudio_host(
                    lm_hosts,
                    local_ip=local_ip,
                    preferred_win_ip=preferred,
                )
                if win_ip:
                    log.debug(
                        "detect_active_tilting_ip: discovered windows=%s via live probe "
                        "(candidates=%s, local=%s)",
                        win_ip,
                        lm_hosts,
                        local_ip,
                    )
                    return f"http://{win_ip}"
            
            fallback = f"http://{subnet}.108"
            log.debug("detect_active_tilting_ip: probe found nothing, fallback windows=%s", fallback)
            return fallback

        def worker():
            """
            Background worker that runs the discovery routine and stores its outcome into a shared result slot.
            
            Attempts to call do_discovery() and assign its return value to result[0]. If an exception occurs, logs a warning and leaves the shared result unchanged.
            """
            try:
                result[0] = do_discovery()
            except Exception as e:
                log.warning("Discovery worker failed: %s", e)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(timeout=25.0)

        if thread.is_alive():
            log.warning("Active tilting IP discovery timed out after 25 seconds; falling back to 192.168.254.108")
            return "http://192.168.254.108"
            
        if result[0]:
            return result[0]
            
        return "http://192.168.254.108"
    except Exception as exc:
        log.warning("Active tilting IP detection failed (%s); falling back to 192.168.254.108", exc)
        return "http://192.168.254.108"


async def main():
    """
    Command-line entry point that runs LAN discovery, loads or saves discovery state, and optionally prompts the user for takeover consent.
    
    Parses the following CLI options and performs their associated actions:
    - --scan: scan the LAN for AI inference servers and save the resulting discovery state.
    - --subnet: specify the CIDR subnet to scan (e.g., 192.168.1.0/24).
    - --interactive: present an interactive consent UI to mark discovered endpoints for orchestrator takeover.
    - --load: load previously saved discovery state and restore discovered endpoints.
    
    Behavior details:
    - When --load is used, previously saved endpoints are appended to the in-memory discovery list.
    - When --scan is used, the subnet (provided or auto-detected) is scanned and results are persisted to the discovery state file.
    - --interactive requires discovered endpoints (from --scan or --load); consenting endpoints are marked and the updated state is saved, with brief next-step instructions printed.
    - If neither --scan nor --load is provided, the function prints the current discovery table and guidance about available actions.
    """
    import argparse
    
    parser = argparse.ArgumentParser(
        description="LAN-wide AI model discovery and orchestration takeover"
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="Scan LAN for AI inference servers",
    )
    parser.add_argument(
        "--subnet",
        type=str,
        help="Subnet to scan in CIDR notation (e.g., 192.168.1.0/24)",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Show interactive consent UI for takeover",
    )
    parser.add_argument(
        "--load",
        action="store_true",
        help="Load previously discovered state",
    )
    
    args = parser.parse_args()
    
    discovery = LANDiscovery(subnet=args.subnet)
    
    if args.load:
        state = discovery.load_discovery_state()
        if state:
            print(f"Loaded discovery state from {state['discovered_at']}")
            for ep_data in state["endpoints"]:
                ep = AIEndpoint(**ep_data)
                discovery.discovered.append(ep)
        else:
            print("No saved discovery state found.")
    
    if args.scan:
        await discovery.scan_lan()
        discovery.save_discovery_state()
    
    if args.interactive:
        if not discovery.discovered and not args.load:
            print("No endpoints discovered. Run with --scan first.")
            return
        
        consented = discovery.interactive_consent()
        
        if consented:
            discovery.save_discovery_state()
            print("\nConsented endpoints saved. Ready for orchestrator integration.")
            print("Next steps:")
            print("  1. Review .state/lan_discovery.json")
            print("  2. Run orchestrator with: python orchestrator.py --distributed")
    
    elif not args.scan and not args.load:
        # Default: show help
        discovery.print_discovery_table()
        print("Run with --scan to discover endpoints, or --interactive for takeover UI.\n")


if __name__ == "__main__":
    asyncio.run(main())
