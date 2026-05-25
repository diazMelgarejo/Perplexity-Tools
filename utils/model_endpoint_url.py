"""Central policy for local/LAN model server base URLs (LM Studio, Ollama, Win coder pool).

Default allow: loopback and RFC1918 private addresses only.
Set ``ALLOW_PUBLIC_MODEL_ENDPOINTS=1`` (or ``true``/``yes``/``on``) to permit public IPs
and non-localhost DNS names.
"""
from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlparse

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_TRUTHY = frozenset({"1", "true", "yes", "on"})


class ModelEndpointPolicyError(ValueError):
    """Raised when a model endpoint URL violates egress policy."""


def allow_public_model_endpoints() -> bool:
    """Return True when public model endpoints are explicitly allowed."""
    return os.getenv("ALLOW_PUBLIC_MODEL_ENDPOINTS", "").strip().lower() in _TRUTHY


def redact_endpoint_for_log(url: str) -> str:
    """Return a log-safe endpoint string (host topology partially hidden)."""
    try:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "?").lower()
        if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost"):
            display = host
        else:
            try:
                ip = ipaddress.ip_address(host)
                if ip.is_private or ip.is_loopback:
                    if isinstance(ip, ipaddress.IPv4Address):
                        parts = str(ip).split(".")
                        display = ".".join(parts[:3]) + ".*" if len(parts) == 4 else "[private-ip]"
                    else:
                        display = "[private-ipv6]"
                else:
                    display = "[public-ip]"
            except ValueError:
                display = "[hostname]"
        port = parsed.port
        if port is None:
            port = 443 if parsed.scheme == "https" else 80
        scheme = parsed.scheme or "http"
        return f"{scheme}://{display}:{port}"
    except Exception:
        return "[invalid-endpoint]"


def _host_allowed(host: str, *, allow_public: bool) -> bool:
    normalized = host.strip().lower()
    if not normalized:
        return False
    if normalized in ("localhost", "::1") or normalized.endswith(".localhost"):
        return True
    if normalized.startswith("127."):
        return True
    try:
        addr = ipaddress.ip_address(normalized)
    except ValueError:
        return allow_public
    if addr.is_loopback or addr.is_private:
        return True
    return allow_public


def validate_model_endpoint_url(
    url: str,
    *,
    allow_public: bool | None = None,
) -> str:
    """Validate and normalize a model server base URL (no path).

    Returns scheme://host[:port] without a trailing slash.
    """
    if allow_public is None:
        allow_public = allow_public_model_endpoints()

    raw = (url or "").strip()
    if not raw:
        raise ModelEndpointPolicyError("empty endpoint URL")

    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise ModelEndpointPolicyError(
            f"endpoint scheme {scheme!r} not allowed (http/https only)"
        )
    if parsed.username or parsed.password:
        raise ModelEndpointPolicyError("credentials in endpoint URL are not allowed")

    host = parsed.hostname
    if not host:
        raise ModelEndpointPolicyError("endpoint URL missing hostname")

    if not _host_allowed(host, allow_public=allow_public):
        raise ModelEndpointPolicyError(
            "endpoint host is not loopback or RFC1918 private "
            f"({redact_endpoint_for_log(raw)}); set ALLOW_PUBLIC_MODEL_ENDPOINTS=1 "
            "to allow public hosts"
        )

    port = parsed.port
    if port is None:
        port = 443 if scheme == "https" else 80

    # Bracket IPv6 literals for urlparse-compatible reconstruction.
    if ":" in host and not host.startswith("["):
        netloc = f"[{host}]:{port}"
    else:
        netloc = f"{host}:{port}"

    return f"{scheme}://{netloc}".rstrip("/")


def parse_model_endpoint_list(
    raw: str,
    *,
    allow_public: bool | None = None,
    skip_invalid: bool = False,
) -> list[str]:
    """Parse a comma-separated endpoint list and validate each base URL."""
    if not raw or not raw.strip():
        return []

    out: list[str] = []
    for part in raw.split(","):
        candidate = part.strip()
        if not candidate or candidate == "REQUIRED_SET_IN_ENV":
            continue
        try:
            out.append(validate_model_endpoint_url(candidate, allow_public=allow_public))
        except ModelEndpointPolicyError:
            if skip_invalid:
                continue
            raise
    return out
