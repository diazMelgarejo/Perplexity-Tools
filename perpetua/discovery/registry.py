from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from .backend import Backend, BackendKind, BackendHealth
from .errors import BackendOfflineError
from .probe import health_probe

# Seed list for autodetect. Pure data — extend without code changes elsewhere.
# HARDWARE POLICY: Mac inference ALWAYS goes through ollama-local (localhost:11434).
# lmstudio-mac (localhost:1234) is a MIRROR ONLY — it proxies Win models but the Mac
# hardware CANNOT run them (qwen3.5-27b is RTX 3080-only). Dispatching inference to
# lmstudio-mac while lmstudio-win is also handling the same model = "double barrel" =
# GPU contention / hardware risk. selector.py enforces mirror exclusion at routing time.
_SEEDS: tuple[tuple[str, str, BackendKind], ...] = (
    ("ollama-local", "http://localhost:11434/v1", BackendKind.OLLAMA),
    ("lmstudio-mac", "http://localhost:1234/v1", BackendKind.LMSTUDIO),   # MIRROR — discovery only
    ("lmstudio-win", "http://192.168.254.103:1234/v1", BackendKind.LMSTUDIO),
)


class BackendRegistry:
    def __init__(self) -> None:
        self._backends: dict[str, Backend] = {}

    def all(self) -> list[Backend]:
        return list(self._backends.values())

    def online(self) -> list[Backend]:
        return [b for b in self._backends.values() if b.health is BackendHealth.ONLINE]

    def find(self, name: str) -> Backend | None:
        return self._backends.get(name)

    async def autodetect(self) -> list[Backend]:
        results = await asyncio.gather(
            *(self._probe_and_record(name, url, kind) for name, url, kind in _SEEDS),
            return_exceptions=False,
        )
        return [b for b in results if b is not None]

    async def register_by_ip(
        self, ip: str, port: int, kind: BackendKind, *, name: str | None = None
    ) -> Backend:
        url = f"http://{ip}:{port}/v1"
        name = name or f"{kind.value}-{ip}"
        backend = await self._probe_and_record(name, url, kind)
        if backend is None or backend.health is not BackendHealth.ONLINE:
            raise BackendOfflineError(f"{name} @ {url} did not respond")
        return backend

    async def _probe_and_record(self, name: str, url: str, kind: BackendKind) -> Backend | None:
        probe = await health_probe(url)
        now = datetime.now(timezone.utc)
        backend = Backend(
            name=name, base_url=url, kind=kind, models=probe.models,
            health=probe.health, last_seen=now,
        )
        if probe.health is BackendHealth.ONLINE:
            self._backends[name] = backend
        return backend
