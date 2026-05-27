#!/usr/bin/env python3
"""
Network auto-configuration helper for orama-system.
Auto-detects a useful LAN address and can scan for PT, ultrathink, LM Studio,
Ollama, and portal services on the local subnet.
"""

import socket
import platform
import subprocess
import re
import os
from typing import Optional, Dict

try:
    import netifaces
    NETIFACES_AVAILABLE = True
except ImportError:
    NETIFACES_AVAILABLE = False

class NetworkAutoConfig:
    def __init__(self):
        self.system = platform.system()
        # Priority 1: read from openclaw.json (authoritative — kept fresh by discover.py).
        # Priority 2: fall back to confirmed hardware constants (last-resort only).
        # OLD stale IPs (archive): Darwin=.110, Windows=.108/.100/.101 — do not restore.
        self.preferred_ips = self._load_from_openclaw() or {
            'Darwin': '192.168.254.105',   # macOS LAN IP (last-resort; use localhost for self-probe)
            'Windows': '192.168.254.105',  # Windows RTX 3080 (last-resort; confirmed 2026-04-26)
        }

    def _load_from_openclaw(self) -> Optional[Dict[str, str]]:
        """
        Read IPs from ~/.openclaw/openclaw.json — the single authoritative store
        that discover.py patches after every successful live probe.
        Returns None if the file is missing or malformed (caller falls back to constants).
        """
        try:
            import json
            from pathlib import Path
            cfg = json.loads(Path.home().joinpath('.openclaw/openclaw.json').read_text())
            providers = cfg.get('models', {}).get('providers', {})
            win_url = providers.get('lmstudio-win', {}).get('baseUrl', '')
            win_ip = win_url.split('//')[-1].split(':')[0] if '//' in win_url else ''
            if not win_ip:
                return None
            return {
                'Darwin': '192.168.254.105',  # Mac LAN identity (probe via localhost)
                'Windows': win_ip,
            }
        except Exception:
            return None

    def get_preferred_ip(self) -> str:
        """Get OS-preferred IP address"""
        return self.preferred_ips.get(self.system, '127.0.0.1')
    
    def detect_active_interfaces(self) -> Dict[str, str]:
        """Detect all active network interfaces and their IPs"""
        interfaces = {}
        
        if NETIFACES_AVAILABLE:
            try:
                for interface in netifaces.interfaces():
                    if interface.startswith(('lo', 'Loopback')):  # Skip loopback
                        continue
                    
                    addrs = netifaces.ifaddresses(interface)
                    if netifaces.AF_INET in addrs:
                        for addr_info in addrs[netifaces.AF_INET]:
                            ip = addr_info['addr']
                            # Skip localhost and APIPA addresses
                            if not ip.startswith('127.') and not ip.startswith('169.254'):
                                interfaces[interface] = ip
                                break
            except Exception as e:
                print(f"Error detecting interfaces via netifaces: {e}")
        
        return interfaces
    
    def get_working_local_ip(self) -> str:
        """Get the working local IP with Mac-first preference"""
        print(f"Detecting IP for {self.system} system...")
        
        # Detect all active interfaces
        interfaces = self.detect_active_interfaces()
        print(f"Active interfaces: {interfaces}")
        
        # Mac-first logic
        if self.system == 'Darwin':
            # Prefer macOS interface if available
            mac_interface = None
            for iface_name, ip in interfaces.items():
                if any(mac_iface in iface_name.lower() for mac_iface in ['en', 'bridge', 'utun']):
                    mac_interface = ip
                    break
            
            if mac_interface:
                print(f"Found Mac interface: {mac_interface}")
                return mac_interface
            else:
                print("No Mac interface found, using preferred IP")
                return self.get_preferred_ip()
        
        # Windows logic
        elif self.system == 'Windows':
            # Look for Windows ethernet/wifi adapters
            win_interface = None
            for iface_name, ip in interfaces.items():
                if any(win_iface in iface_name.lower() for win_iface in ['ethernet', 'wi-fi', 'wlan', 'eth']):
                    win_interface = ip
                    break
            
            if win_interface:
                print(f"Found Windows interface: {win_interface}")
                return win_interface
            else:
                print("No Windows interface found, using preferred IP")
                return self.get_preferred_ip()
        
        # Fallback to any active interface
        if interfaces:
            first_ip = next(iter(interfaces.values()))
            print(f"Using first available interface: {first_ip}")
            return first_ip
        
        # Ultimate fallback
        fallback_ip = self.get_preferred_ip()
        print(f"Using fallback IP: {fallback_ip}")
        return fallback_ip
    
    def verify_connectivity(self, ip: str, port: int = 8000) -> bool:
        """Verify that the IP is actually working"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((ip, port))
            sock.close()
            return result == 0
        except Exception:
            return False
    
    # ── LAN agent discovery ────────────────────────────────────────────────
    # Ports to probe per service type
    AGENT_PORTS: Dict[str, int] = {
        "lmstudio": 1234,
        "ollama": 11434,
        "ultrathink": 8001,
        "perplexity": 8000,
        "portal": 8002,
    }

    def _get_subnet_prefix(self, ip: str) -> str:
        """Return /24 prefix (e.g. '192.168.254') from an IP."""
        parts = ip.rsplit(".", 1)
        return parts[0] if len(parts) == 2 else "192.168.1"

    def discover_lan_agents(
        self,
        subnet_prefix: Optional[str] = None,
        services: Optional[list] = None,
        scan_timeout: float = 0.3,
    ) -> Dict[str, list]:
        """
        Scan the LAN subnet for running agent instances (LM Studio, Ollama, etc.).
        Reuses verify_connectivity() for each host:port pair.

        Returns dict: service_name → [list of reachable IPs]
        e.g. {"lmstudio": ["192.168.254.105"], "ollama": ["192.168.254.105"]}
        """
        if subnet_prefix is None:
            local_ip = self.get_working_local_ip()
            subnet_prefix = self._get_subnet_prefix(local_ip)

        if services is None:
            services = list(self.AGENT_PORTS.keys())

        results: Dict[str, list] = {svc: [] for svc in services}

        for last_octet in range(1, 255):
            host = f"{subnet_prefix}.{last_octet}"
            for svc in services:
                port = self.AGENT_PORTS[svc]
                # reuse existing verify_connectivity with short timeout
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(scan_timeout)
                try:
                    if sock.connect_ex((host, port)) == 0:
                        results[svc].append(host)
                except Exception:
                    pass
                finally:
                    sock.close()

        return results

    def get_optimal_server_config(self) -> Dict[str, str]:
        """Get optimal server configuration based on detected network"""
        ip = self.get_working_local_ip()
        
        # Verify connectivity
        if self.verify_connectivity(ip):
            print(f"Verified connectivity for {ip}")
        else:
            print(f"Warning: Could not verify connectivity for {ip}")
        
        config = {
            'host': ip,
            'port': '8000',
            'bind_address': f"{ip}:8000"
        }
        
        return config

def main():
    print("=== Network Auto-Configuration for orama-system ===")

    configurer = NetworkAutoConfig()
    config = configurer.get_optimal_server_config()

    print(f"\nRecommended Server Configuration:")
    print(f"  Host: {config['host']}")
    print(f"  Port: {config['port']}")
    print(f"  Bind Address: {config['bind_address']}")

    # Export as environment variables (for use in shell scripts)
    print(f"\nExport these for your shell:")
    print(f"export HOST={config['host']}")
    print(f"export PORT={config['port']}")

    # LAN agent discovery (hint: add --scan flag to enable)
    import sys
    if "--scan" in sys.argv:
        print("\nScanning LAN for running agents (this may take ~30s)...")
        agents = configurer.discover_lan_agents()
        print("\nDiscovered agents:")
        for svc, hosts in agents.items():
            if hosts:
                print(f"  {svc}: {', '.join(hosts)}")
        if not any(agents.values()):
            print("  (none found)")
    else:
        print("\nTip: run with --scan to discover running LM Studio / Ollama instances on LAN")

if __name__ == "__main__":
    main()
