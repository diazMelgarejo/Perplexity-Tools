from __future__ import annotations
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from urllib.parse import urlparse


class BackendKind(str, Enum):
    OLLAMA = "ollama"
    LMSTUDIO = "lmstudio"
    OPENROUTER = "openrouter"


class BackendHealth(str, Enum):
    UNKNOWN = "unknown"
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class Backend:
    name: str
    base_url: str
    kind: BackendKind
    models: tuple[str, ...] = field(default_factory=tuple)
    health: BackendHealth = BackendHealth.UNKNOWN
    last_seen: datetime | None = None

    @property
    def host(self) -> str:
        return urlparse(self.base_url).hostname or ""

    def is_targetable_by_ip(self, ip: str) -> bool:
        return self.host == ip

    def with_health(self, health: BackendHealth, *, now: datetime) -> "Backend":
        return replace(self, health=health, last_seen=now)
