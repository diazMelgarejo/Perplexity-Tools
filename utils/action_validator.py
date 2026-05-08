"""Two-phase action validation gate — V1 adaptation.

Derived from Anthropic multi-agent pattern §2c (v2/5-Anthropic-agent-design.md).
Adapted for V1: no DB, MAESTRO gate classes defined but enforcement is log-only
until v2.5 ships the full cryptographic token flow.

Gate classes (MAESTRO v2.5 forward):
  Class 2 — intent log + user confirm
  Class 3 — human approval token required
  Class 4 — cryptographic token + immutable audit entry

V1 behaviour:
  - Class 2: auto-approved (logged only)
  - Class 3: raises PermissionError with gate_class=3 in response dict
  - Class 4: raises PermissionError with gate_class=4

Wire into supervisor._run_worker() before any tool call.
"""
from __future__ import annotations

from utils.hardware_policy import HardwareAffinityError, check_affinity


class ActionValidator:
    """
    Two-phase validate-then-execute gate.

    Phase 1: hardware affinity policy (uses existing HardwarePolicyResolver)
    Phase 2a: irreversibility check → gate_class=4
    Phase 2b: HITL scope check    → gate_class=3
    """

    # Actions that cannot be undone — require cryptographic token in v2.5
    IRREVERSIBLE: frozenset[str] = frozenset({
        "delete_file",
        "drop_table",
        "kill_process",
        "push_to_remote",
        "format_disk",
        "truncate_log",
    })

    # Actions requiring human confirmation before execution
    REQUIRES_HITL: frozenset[str] = frozenset({
        "send_message",
        "execute_financial_query",
        "modify_model_registry",
        "update_hardware_policy",
        "restart_backend",
    })

    def validate(self, action: dict) -> dict:
        """
        Run both validation phases and return a result dict.

        Returns:
            {"status": "approved", "gate_class": None}
            {"status": "rejected", "reason": str, "gate_class": None}
            {"status": "requires_confirmation", "reason": str, "gate_class": int}
        """
        tool     = action.get("tool", "")
        model    = action.get("model", "")
        platform = action.get("platform", "mac")

        # Phase 1: hardware affinity policy
        if model:
            try:
                check_affinity(model, platform)
            except HardwareAffinityError as exc:
                return {"status": "rejected", "reason": str(exc), "gate_class": None}

        # Phase 2a: irreversibility (gate 4)
        if tool in self.IRREVERSIBLE:
            return {
                "status": "requires_confirmation",
                "reason": (
                    f"'{tool}' is irreversible — human approval token required "
                    "(MAESTRO Class 4)"
                ),
                "gate_class": 4,
            }

        # Phase 2b: HITL scope (gate 3)
        if tool in self.REQUIRES_HITL:
            return {
                "status": "requires_confirmation",
                "reason": (
                    f"'{tool}' requires human approval "
                    "(MAESTRO Class 3)"
                ),
                "gate_class": 3,
            }

        return {"status": "approved", "gate_class": None}

    def execute(self, action: dict, validator_result: dict, execute_fn) -> dict:
        """Execute only if the validator approved.  Raises PermissionError otherwise."""
        if validator_result["status"] != "approved":
            raise PermissionError(validator_result["reason"])
        return execute_fn(action["tool"], action.get("args", {}))
