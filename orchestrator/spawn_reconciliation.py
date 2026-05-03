#!/usr/bin/env python3
"""
orchestrator/spawn_reconciliation.py
------------------------------------
Recruits existing/orphaned agent spawns (ECC, autoresearch) back into 
Perpetua-Tools management.

Features:
- Detects orphaned processes on LAN machines.
- Reconciles detected spawns against .state/agents.json registry.
- Resumes roles or re-assigns them based on current task needs.
"""

import json
import asyncio
import time
from pathlib import Path
from typing import List, Dict, Optional
from .agent_tracker import AgentTracker, AgentRecord
from .lan_discovery import LANDiscovery, AIEndpoint

class SpawnReconciler:
    def __init__(self, tracker: AgentTracker, discovery: LANDiscovery):
        self.tracker = tracker
        self.discovery = discovery

    async def reconcile_orphans(self) -> List[AgentRecord]:
        """
        Scan LAN for AI endpoints, check against registry, and recruit orphans.
        """
        # 1. Scan for all available AI endpoints on LAN
        endpoints = await self.discovery.scan_lan()
        
        # 2. Load existing registry
        known_agents = self.tracker.list_agents()
        known_endpoints = {f"{a.host}:{a.port}" for a in known_agents if a.status in ["running", "idle"]}
        
        recruited = []
        
        for ep in endpoints:
            ep_key = f"{ep.host}:{ep.port}"
            
            # 3. Check if this is a known, currently managed endpoint
            if ep_key in known_endpoints:
                continue
                
            # 4. It's an orphan or new spawn. Check if it matches a previously recorded agent
            # (e.g. registry says it should be running but status was 'starting' or 'error')
            potential_match = self._find_registry_match(ep, known_agents)
            
            if potential_match:
                # Resume previous role
                updated = self.tracker.update_status(potential_match.agent_id, "running")
                if updated is None:
                    continue  # agent disappeared between scan and update
                print(f"[reconciler] Recruited orphaned agent {updated.agent_id} as {updated.role}")
                recruited.append(updated)
            else:
                # 5. It's a brand new discovery (e.g. ECC spawn not in our registry)
                # Register it with a default role or based on server type
                new_role = self._infer_role(ep)
                new_agent = self.tracker.register(
                    role=new_role,
                    model=ep.models[0] if ep.models else "unknown",
                    backend=ep.server_type,
                    host=ep.host,
                    port=ep.port,
                    metadata={"source": "lan_discovery_recruit"}
                )
                updated_new = self.tracker.update_status(new_agent.agent_id, "running")
                print(f"[reconciler] Registered and recruited new spawn {new_agent.agent_id} as {new_role}")
                recruited.append(updated_new or new_agent)
                
        return recruited

    def _find_registry_match(self, ep: AIEndpoint, known_agents: List[AgentRecord]) -> Optional[AgentRecord]:
        """Search for a known agent record that matches this endpoint's host/port."""
        for agent in known_agents:
            if agent.host == ep.host and agent.port == ep.port:
                return agent
        return None

    def _infer_role(self, ep: AIEndpoint) -> str:
        """Infer a suitable role for a newly discovered spawn."""
        if "coder" in "".join(ep.models).lower():
            return "recruited-coder"
        if ep.server_type == "ollama":
            return "recruited-reasoner"
        return "recruited-agent"

async def main():
    tracker = AgentTracker()
    discovery = LANDiscovery()
    reconciler = SpawnReconciler(tracker, discovery)
    
    print("[reconciler] Starting spawn reconciliation...")
    recruited = await reconciler.reconcile_orphans()
    print(f"[reconciler] Reconciliation complete. Recruited {len(recruited)} agents.")

if __name__ == "__main__":
    asyncio.run(main())
