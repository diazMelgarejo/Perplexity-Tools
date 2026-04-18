# 04. Gateway Discovery — Commandeer-First Bootstrap

**TL;DR:** Probe all candidate ports before installing. If a compatible gateway answers `/health`, commandeer it — never start a duplicate or restart a running daemon.

---

## Root Cause (2026-04-07)

Old bootstrap only checked `127.0.0.1:18789`. AlphaClaw or other OpenClaw-compatible forks on alternate ports caused a second daemon to spawn, conflicting with already-loaded agents.

---

## PT-Specific Files

`alphaclaw_bootstrap.py` — gateway lifecycle management entry point.

```python
# alphaclaw_bootstrap.py
OPENCLAW_CANDIDATE_PORTS = [18789, 11435, 8080, 3000]

async def _find_running_gateway() -> str | None:
    extra = os.environ.get("OPENCLAW_EXTRA_PORTS", "")
    ports = OPENCLAW_CANDIDATE_PORTS + [int(p) for p in extra.split(",") if p.strip()]
    for port in ports:
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=2)
            if r.status_code < 500:
                return f"http://127.0.0.1:{port}"
        except Exception:
            continue
    return None

async def bootstrap_alphaclaw():
    existing = await _find_running_gateway()
    if existing:
        os.environ["OPENCLAW_GATEWAY_URL"] = existing
        await _refresh_openclaw_config(existing)  # update config only
        return  # DO NOT restart
    await _full_install_and_start()
```

---

## Rules

1. **Probe before install** — check all candidate ports first
2. **Commandeer-first, install-last** — use any compatible service on localhost
3. **Never call `onboard --install-daemon` on a running gateway** — evicts loaded models
4. **Set `OPENCLAW_GATEWAY_URL`** env var after discovery
5. **Probe by interface** — `/health` or `/v1/models`, not process name

---

## Commit
- `6bc40d0` (UTS) — feat(bootstrap): probe all candidate ports and commandeer any running gateway

## Related

- [Session log 2026-04-07](../LESSONS.md#2026-04-07--claude--idempotent-gateway-discovery-commandeer-first-bootstrap)
- [UTS/04](https://github.com/diazMelgarejo/ultrathink-system/blob/main/docs/wiki/04-gateway-discovery.md) — full code examples
- [AlphaClaw wiki/03-gateway-config.md](https://github.com/diazMelgarejo/AlphaClaw/blob/feature/MacOS-post-install/docs/wiki/03-gateway-config.md)
