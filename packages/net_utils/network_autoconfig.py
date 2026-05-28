#!/usr/bin/env python3
"""
Network auto-configuration helper for orama-system.
Auto-detects a useful LAN address and can scan for PT, ultrathink, LM Studio,
Ollama, and portal services on the local subnet.
"""

import logging
import socket
import platform
import subprocess
import re
import os
from typing import Optional, Dict

log = logging.getLogger(__name__)

try:
    import netifaces
    NETIFACES_AVAILABLE = True
except ImportError:
    NETIFACES_AVAILABLE = False
    log.debug("netifaces not installed; install perpetua-tools[lan] for interface-aware IP detection")

class NetworkAutoConfig:
    def __init__(self):
        """
        Initialize the NetworkAutoConfig instance by detecting the host operating system and establishing a prioritized mapping of preferred LAN IPs.
        
        If available, preferred IPs are loaded from the user's OpenClaw configuration via _load_from_openclaw(); otherwise a last-resort fallback mapping is used:
        - Darwin: 192.168.254.105
        - Windows: 192.168.254.105
        
        Sets:
        - self.system: detected platform name (e.g., 'Darwin', 'Windows')
        - self.preferred_ips: dict mapping OS names to preferred LAN IPs (authoritative source preferred, fallbacks used only if loading fails)
        """
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
        Load preferred IPs from ~/.openclaw/openclaw.json by extracting the LM Studio base URL.
        
        Returns:
            dict: Mapping of OS name to IP string (e.g., {'Darwin': '192.168.254.105', 'Windows': '<ip>'}) when a usable LM Studio IP is found.
            None: If the file is missing, malformed, or does not contain a usable LM Studio IP.
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
        """
        Get the preferred IP address for the current operating system.
        
        Returns:
            str: Preferred IP address for the current OS, or '127.0.0.1' if no preference is configured.
        """
        return self.preferred_ips.get(self.system, '127.0.0.1')
    
    def detect_active_interfaces(self) -> Dict[str, str]:
        """
        Return a mapping of active network interface names to their detected IPv4 addresses.
        
        Scans system network interfaces (when the optional `netifaces` module is available) and collects the first non-localhost, non-APIPA IPv4 address found for each non-loopback interface. If `netifaces` is not available, an empty dict is returned. If an error occurs during scanning, any successfully collected interfaces are returned and a warning is logged.
        
        Returns:
            Dict[str, str]: Mapping from interface name to its selected IPv4 address; empty if none detected or if interface-aware detection is unavailable.
        """
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
                log.warning("netifaces interface scan failed: %s", e)
        else:
            log.debug(
                "netifaces unavailable — detect_active_interfaces() returning empty dict; "
                "install perpetua-tools[lan] to enable interface-aware detection"
            )
        return interfaces
    
    def get_working_local_ip(self) -> str:
        """
        Selects the most appropriate local IPv4 address for the current operating system.
        
        For macOS, prefers an interface whose name contains 'en', 'bridge', or 'utun'.
        For Windows, prefers an interface whose name contains 'ethernet', 'wi-fi', 'wlan', or 'eth'.
        For other systems, uses the first detected non-loopback IPv4 address.
        If no suitable interface is found, returns the configured preferred IP.
        
        Returns:
            chosen_ip (str): The selected IPv4 address in dotted-quad form.
        """
        log.debug("Detecting IP for %s system…", self.system)

        interfaces = self.detect_active_interfaces()
        log.debug("Active interfaces: %s", interfaces)

        # Mac-first logic
        if self.system == 'Darwin':
            for iface_name, ip in interfaces.items():
                if any(token in iface_name.lower() for token in ('en', 'bridge', 'utun')):
                    log.debug("Found Mac interface %s → %s", iface_name, ip)
                    return ip
            log.debug("No Mac interface found — using preferred IP")
            return self.get_preferred_ip()

        # Windows logic
        if self.system == 'Windows':
            for iface_name, ip in interfaces.items():
                if any(token in iface_name.lower() for token in ('ethernet', 'wi-fi', 'wlan', 'eth')):
                    log.debug("Found Windows interface %s → %s", iface_name, ip)
                    return ip
            log.debug("No Windows interface found — using preferred IP")
            return self.get_preferred_ip()

        # Any active interface
        if interfaces:
            first_ip = next(iter(interfaces.values()))
            log.debug("Using first available interface: %s", first_ip)
            return first_ip

        # Ultimate fallback
        fallback_ip = self.get_preferred_ip()
        log.debug("No interfaces detected — using fallback IP: %s", fallback_ip)
        return fallback_ip
    
    def verify_connectivity(self, ip: str, port: int = 8000) -> bool:
        """
        Check TCP reachability for the given IP and port.
        
        Returns:
            `true` if a TCP connection to the given IP and port could be established, `false` otherwise.
        """
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
        """
        Get the /24 subnet prefix (first three octets) from an IPv4 address string.
        
        Parameters:
            ip (str): IPv4 address in dotted-decimal form (e.g., "192.168.254.105").
        
        Returns:
            str: The subnet prefix (e.g., "192.168.254"). Returns "192.168.1" if the input is not a valid dotted IPv4 string.
        """
        parts = ip.rsplit(".", 1)
        return parts[0] if len(parts) == 2 else "192.168.1"

    def discover_lan_agents(
        self,
        subnet_prefix: Optional[str] = None,
        services: Optional[list] = None,
        scan_timeout: float = 0.3,
    ) -> Dict[str, list]:
        """
        Scan a /24 LAN subnet for reachable agent services and return discovered host IPs per service.
        
        Parameters:
            subnet_prefix (Optional[str]): First three octets of the subnet (e.g. "192.168.1"). If omitted, the method derives the prefix from the system's working local IP.
            services (Optional[list]): List of service names to probe (keys of `AGENT_PORTS`). If omitted, all known services are probed.
            scan_timeout (float): Socket timeout in seconds for each probe.
        
        Returns:
            Dict[str, list]: Mapping from service name to a list of reachable IPv4 addresses (as strings). For example: {"lmstudio": ["192.168.254.105"], "ollama": []}
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
        """
        Builds a recommended server configuration using the detected local IP.
        
        Attempts to verify TCP connectivity to the chosen IP on port 8000; verification failures are logged but do not prevent returning the configuration.
        
        Returns:
            config (Dict[str, str]): Mapping with keys:
                - 'host': selected local IP address.
                - 'port': port number as a string ('8000').
                - 'bind_address': host and port combined as "host:8000".
        """
        ip = self.get_working_local_ip()
        if self.verify_connectivity(ip):
            log.debug("Verified connectivity for %s", ip)
        else:
            log.warning("Could not verify connectivity for %s — continuing anyway", ip)
        return {
            'host': ip,
            'port': '8000',
            'bind_address': f"{ip}:8000",
        }

def main():
    """
    Prints a recommended server configuration and, when requested, scans the local network for known agents.
    
    Uses NetworkAutoConfig to determine a preferred working local IP and builds a host/port/bind_address recommendation, which is printed along with shell export lines for HOST and PORT. If the command-line flag `--scan` is present, performs a LAN scan for known service ports and prints discovered agent IPs (may take about 30 seconds).
    """
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
