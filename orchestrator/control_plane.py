from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from orchestrator import autoresearch_bridge
from orchestrator.perplexity_client import ensure_credentials

DEFAULT_RUNTIME_STATE_PATH = Path(".state/runtime_payload.json")
RUNTIME_SCHEMA_VERSION = "pt-first-orchestrator-v1"


@dataclass
class StageReport:
    name: str
    status: str
    detail: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


def _stage(name: str, status: str, detail: str = "", **meta: Any) -> dict[str, Any]:
    return asdict(StageReport(name=name, status=status, detail=detail, meta=meta))


def save_runtime_payload(payload: dict[str, Any], path: str | Path | None = None) -> Path:
    runtime_path = Path(path or DEFAULT_RUNTIME_STATE_PATH)
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return runtime_path


def load_runtime_payload(path: str | Path | None = None) -> dict[str, Any] | None:
    runtime_path = Path(
        path
        or os.getenv("PT_RUNTIME_STATE", "")
        or DEFAULT_RUNTIME_STATE_PATH
    )
    if not runtime_path.exists():
        return None
    return json.loads(runtime_path.read_text(encoding="utf-8"))


async def resolve_routing_state() -> dict[str, Any]:
    import agent_launcher

    routing_state = await agent_launcher.initialize_environment()
    agent_launcher.save_routing_state(routing_state)
    return routing_state


async def reconcile_gateway(force: bool = False) -> dict[str, Any]:
    import alphaclaw_bootstrap

    return await alphaclaw_bootstrap.bootstrap_alphaclaw(force=force)


def preflight_autoresearch(
    *,
    run_tag: str | None = None,
    gateway_ready: bool = False,
) -> dict[str, Any]:
    result = autoresearch_bridge.preflight(run_tag=run_tag)
    handshake = [
        {
            "stage": "openclaw_ready",
            "ok": gateway_ready,
            "detail": (
                "OpenClaw/AlphaClaw gateway ready."
                if gateway_ready
                else "Gateway not confirmed ready before autoresearch preflight."
            ),
        },
        {
            "stage": "autoresearch_sync",
            "ok": bool(result.get("sync_ok")),
            "detail": (
                f"autoresearch synced to {result.get('sha', '')[:7]}"
                if result.get("sync_ok")
                else result.get("error", "Autoresearch sync failed.")
            ),
        },
        {
            "stage": "swarm_state_ready",
            "ok": bool(result.get("swarm_state_initialised") or autoresearch_bridge.SWARM_STATE_FILE.exists()),
            "detail": (
                "swarm_state.md present."
                if result.get("swarm_state_initialised") or autoresearch_bridge.SWARM_STATE_FILE.exists()
                else "swarm_state.md not initialised."
            ),
        },
    ]
    result["handshake"] = handshake
    result["ready"] = all(stage["ok"] for stage in handshake)
    return result


async def bootstrap_runtime(
    *,
    interactive: bool = True,
    validate_perplexity: bool = True,
    allow_web_fallback: bool = True,
    force_gateway: bool = False,
    run_autoresearch_preflight: bool = True,
    runtime_state_path: str | Path | None = None,
    run_tag: str | None = None,
    print_progress: bool = True,
) -> dict[str, Any]:
    started_at = time.time()
    stages: list[dict[str, Any]] = []

    if print_progress:
        print("[orchestrator] Stage 1/4 \u2192 Perplexity credential onboarding")
    credentials = ensure_credentials(
        validate=validate_perplexity,
        interactive=interactive,
        allow_web_fallback=allow_web_fallback,
    )
    stages.append(
        _stage(
            "perplexity_credentials",
            "ready" if credentials["configured"] else "warning",
            credentials["message"],
            auth_mode=credentials["auth_mode"],
            ready_for_api=credentials["ready_for_api"],
        )
    )

    if print_progress:
        print("[orchestrator] Stage 2/4 \u2192 Hardware routing resolution")
    routing_state = await resolve_routing_state()
    stages.append(
        _stage(
            "routing",
            "ready",
            (
                f"manager={routing_state['manager_backend']} "
                f"coder={routing_state['coder_backend']}"
            ),
            distributed=bool(routing_state.get("distributed")),
        )
    )

    os.environ["PT_AGENTS_STATE"] = str(Path(".state/routing.json").resolve())

    if print_progress:
        print("[orchestrator] Stage 3/4 \u2192 AlphaClaw/OpenClaw reconciliation")
    gateway = await reconcile_gateway(force=force_gateway)
    stages.append(
        _stage(
            "gateway",
            "ready" if gateway.get("ok") else "error",
            gateway.get("error") or gateway.get("gateway_url", ""),
            gateway_ready=bool(gateway.get("gateway_ready")),
            commandeered=bool(gateway.get("commandeered")),
        )
    )

    if run_autoresearch_preflight:
        if print_progress:
            print("[orchestrator] Stage 4/4 \u2192 AutoResearch preflight")
        autoresearch = preflight_autoresearch(
            run_tag=run_tag,
            gateway_ready=bool(gateway.get("gateway_ready")),
        )
        stages.append(
            _stage(
                "autoresearch",
                "ready" if autoresearch.get("ready") else "warning",
                autoresearch.get("error") or autoresearch.get("sha", ""),
                sync_ok=bool(autoresearch.get("sync_ok")),
            )
        )
    else:
        autoresearch = {
            "sync_ok": False,
            "ready": False,
            "skipped": True,
            "handshake": [
                {
                    "stage": "autoresearch_sync",
                    "ok": False,
                    "detail": "Autoresearch preflight skipped.",
                }
            ],
        }
        stages.append(
            _stage(
                "autoresearch",
                "skipped",
                "Autoresearch preflight skipped.",
            )
        )

    payload = {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "generated_at": started_at,
        "paths": {
            "pt_root": str(Path(".").resolve()),
            "routing_state": str(Path(".state/routing.json").resolve()),
        },
        "credentials": credentials,
        "routing": routing_state,
        "role_routing": gateway.get("role_routing") or {},
        "gateway": gateway,
        "autoresearch": autoresearch,
        "stages": stages,
    }
    runtime_path = save_runtime_payload(payload, path=runtime_state_path)
    payload["paths"]["runtime_state"] = str(runtime_path.resolve())
    save_runtime_payload(payload, path=runtime_path)
    return payload


def bootstrap_runtime_sync(**kwargs: Any) -> dict[str, Any]:
    return asyncio.run(bootstrap_runtime(**kwargs))
