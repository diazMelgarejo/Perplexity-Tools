from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict


_DEFAULT_BUDGET = {
    "daily_budget": 25.0,
    "daily_spend": 0.0,
    "last_reset": 0.0,
}


class CostGuard:
    """
    File-persisted daily budget guard.
    Auto-resets every 24h. Blocks orchestration when daily_spend ≥ daily_budget.
    Alert triggers at 80% of daily_budget (matching monitoring_config in strategy JSON).
    """

    ALERT_RATIO = 0.80

    def __init__(
        self, state_dir: str = ".state", budget_file: str = "budget.json"
    ) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.budget_path = self.state_dir / budget_file
        self._memory_state: Dict[str, float] = {**_DEFAULT_BUDGET, "last_reset": time.time()}
        self._persist_enabled = True

    def _load(self) -> Dict[str, float]:
        if not self._persist_enabled:
            return dict(self._memory_state)

        try:
            if not self.budget_path.exists():
                payload = {**_DEFAULT_BUDGET, "last_reset": time.time()}
                self._save(payload)
                return payload
            payload = json.loads(self.budget_path.read_text(encoding="utf-8"))
            self._memory_state = dict(payload)
            return payload
        except OSError:
            self._persist_enabled = False
            return dict(self._memory_state)

    def _save(self, payload: Dict[str, float]) -> None:
        self._memory_state = dict(payload)
        if not self._persist_enabled:
            return
        try:
            self.budget_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            self._persist_enabled = False

    def _maybe_reset(self, payload: Dict[str, float]) -> Dict[str, float]:
        if time.time() - payload["last_reset"] >= 86400:
            payload["daily_spend"] = 0.0
            payload["last_reset"] = time.time()
            self._save(payload)
        return payload

    def can_spend(self, estimated_cost: float) -> bool:
        p = self._maybe_reset(self._load())
        return (p["daily_spend"] + estimated_cost) <= p["daily_budget"]

    def alert_approaching(self) -> bool:
        p = self._maybe_reset(self._load())
        return p["daily_spend"] >= (p["daily_budget"] * self.ALERT_RATIO)

    def record_spend(self, amount: float) -> Dict[str, float]:
        p = self._maybe_reset(self._load())
        p["daily_spend"] = round(p["daily_spend"] + amount, 6)
        self._save(p)
        return p

    def snapshot(self) -> Dict[str, Any]:
        p = self._maybe_reset(self._load())
        out: Dict[str, Any] = dict(p)
        out["alert"] = self.alert_approaching()
        out["remaining"] = round(p["daily_budget"] - p["daily_spend"], 6)
        return out

    def set_budget(self, daily_budget: float) -> None:
        p = self._load()
        p["daily_budget"] = daily_budget
        self._save(p)
