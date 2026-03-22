from __future__ import annotations

import json
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class AgentRecord:
    agent_id: str
    role: str
    model: str
    backend: str
    host: str
    port: int
    status: str  # starting | running | idle | stopped | error
    created_at: float
    updated_at: float
    task_hash: Optional[str] = None
    parent_agent_id: Optional[str] = None
    metadata: Dict = field(default_factory=dict)


class AgentTracker:
    """
    Idempotent agent lifecycle manager.
    Persists agent state to .state/agents.json so it survives process restarts.
    Before creating a new agent, always call find_existing() — if a running agent
    is found for the same role/task, the orchestrator should ask the user before
    spawning another one.
    """

    def __init__(self, state_dir: str = ".state") -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.state_dir / "agents.json"

    # ── persistence ──────────────────────────────────────────────────────────

    def _load(self) -> Dict[str, AgentRecord]:
        if not self.registry_path.exists():
            return {}
        raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
        return {k: AgentRecord(**v) for k, v in raw.items()}

    def _save(self, agents: Dict[str, AgentRecord]) -> None:
        payload = {k: asdict(v) for k, v in agents.items()}
        self.registry_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # ── queries ───────────────────────────────────────────────────────────────

    def list_agents(self, status: Optional[str] = None) -> List[AgentRecord]:
        agents = list(self._load().values())
        if status:
            agents = [a for a in agents if a.status == status]
        return agents

    def find_existing(
        self,
        role: str,
        task_hash: Optional[str] = None,
    ) -> Optional[AgentRecord]:
        """Return the first live agent matching role (and optionally task_hash)."""
        for agent in self._load().values():
            if agent.role == role and agent.status in {"starting", "running", "idle"}:
                if task_hash is None or agent.task_hash == task_hash:
                    return agent
        return None

    def detect_conflicts(self) -> List[AgentRecord]:
        """Return agents that are running but may conflict (duplicate roles)."""
        running = self.list_agents(status="running") + self.list_agents(status="idle")
        role_counts = Counter(a.role for a in running)
        return [a for a in running if role_counts[a.role] > 1]

    # ── mutations ────────────────────────────────────────────────────────────

    def register(
        self,
        role: str,
        model: str,
        backend: str,
        host: str,
        port: int,
        task_hash: Optional[str] = None,
        parent_agent_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> AgentRecord:
        agents = self._load()
        now = time.time()
        agent = AgentRecord(
            agent_id=str(uuid.uuid4()),
            role=role,
            model=model,
            backend=backend,
            host=host,
            port=port,
            status="starting",
            created_at=now,
            updated_at=now,
            task_hash=task_hash,
            parent_agent_id=parent_agent_id,
            metadata=metadata or {},
        )
        agents[agent.agent_id] = agent
        self._save(agents)
        return agent

    def update_status(self, agent_id: str, status: str) -> Optional[AgentRecord]:
        agents = self._load()
        agent = agents.get(agent_id)
        if not agent:
            return None
        agent.status = status
        agent.updated_at = time.time()
        agents[agent_id] = agent
        self._save(agents)
        return agent

    def destroy(self, agent_id: str) -> bool:
        """Remove agent from registry when no longer needed."""
        agents = self._load()
        if agent_id not in agents:
            return False
        del agents[agent_id]
        self._save(agents)
        return True

    def destroy_stopped(self) -> int:
        """GC: remove all agents with status=stopped or status=error."""
        agents = self._load()
        before = len(agents)
        agents = {k: v for k, v in agents.items() if v.status not in {"stopped", "error"}}
        self._save(agents)
        return before - len(agents)
