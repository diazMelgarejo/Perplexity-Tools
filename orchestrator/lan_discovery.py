#!/usr/bin/env python3
"""
orchestrator/lan_discovery.py
-----------------------------
LAN-wide AI model discovery and orchestration takeover system.

Scans the local network for running AI inference servers (Ollama, LM Studio, MLX)
and presents a user-consent UI for selective or full takeover by Perplexity-Tools.

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
        
        print("\nPerplexity-Tools can take over these AI endpoints for distributed orchestration.")
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


def detect_active_tilting_ip() -> str:
    """Derive the Windows GPU endpoint base URL from the local subnet at runtime.

    Implements the v0.9.9.5 Active Tilting spec: Windows is always .103 on whatever
    subnet the Mac is on, so the IP is portable across legacy (192.168.1.x) and
    current (192.168.254.x) network topologies without any config change.

    Priority order (mirrors LAN_GPU_IP_OVERRIDE from the hardware matrix):
      1. LAN_GPU_IP_OVERRIDE env var — absolute override, any subnet
      2. LM_STUDIO_WIN_ENDPOINTS env var — backward-compat with existing .env files
      3. UDP routing trick (no packets sent) — live detection of outbound interface
      4. Hardcoded 192.168.254.103 — current-subnet safe fallback

    Returns a base URL string like "http://192.168.254.103" (no port, no path).
    Callers append the port themselves to keep the function backend-agnostic.

    Table:
      Detected subnet   | Derived Windows IP
      192.168.1.x       | 192.168.1.103   (legacy)
      192.168.254.x     | 192.168.254.103 (current)
      <any other /24>   | <subnet>.103
    """
    for env_var in ("LAN_GPU_IP_OVERRIDE", "LM_STUDIO_WIN_ENDPOINTS"):
        val = os.environ.get(env_var, "")
        if val:
            return val if val.startswith("http") else f"http://{val}"
    try:
        import socket as _socket
        with _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))   # No packets are actually sent
            local_ip = s.getsockname()[0]
        subnet = ".".join(local_ip.split(".")[:3])
        detected = f"http://{subnet}.103"   # Windows RTX 3080 is always .103 on any subnet
        log.debug("detect_active_tilting_ip: local=%s → windows=%s", local_ip, detected)
        return detected
    except Exception as exc:
        log.warning("Active tilting IP detection failed (%s); falling back to 192.168.254.103", exc)
        return "http://192.168.254.103"


async def main():
    """
    CLI entry point for LAN discovery.
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
