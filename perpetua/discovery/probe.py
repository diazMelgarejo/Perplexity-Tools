from __future__ import annotations
from dataclasses import dataclass
import httpx
from .backend import BackendHealth

_TIMEOUT_S = 1.5


@dataclass(frozen=True, slots=True)
class ProbeResult:
    health: BackendHealth
    models: tuple[str, ...]


async def health_probe(base_url: str, *, timeout: float = _TIMEOUT_S) -> ProbeResult:
    url = base_url.rstrip("/") + "/models"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url)
    except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError):
        return ProbeResult(BackendHealth.OFFLINE, ())
    if r.status_code != 200:
        return ProbeResult(BackendHealth.OFFLINE, ())
    try:
        body = r.json()
        models = tuple(item["id"] for item in body.get("data", []) if "id" in item)
    except (ValueError, KeyError, TypeError):
        return ProbeResult(BackendHealth.DEGRADED, ())
    return ProbeResult(BackendHealth.ONLINE, models)
