# 03. Device Identity & GPU Crash Recovery

**TL;DR:** One inference backend per physical device. 30-second cooldown after any GPU crash. Probe local IPs before trusting any "remote" endpoint URL.

---

## Root Cause (2026-04-07)

`WINDOWS_IP` was misconfigured to the Mac's own LAN IP → probe succeeded → system treated one Mac as a two-node cluster → two models loaded simultaneously on same GPU. Rapid retry on 503/404 burned GPU with repeated model load/unload cycles.

---

## PT-Specific Context

PT's `orchestrator/control_plane.py` and `agent_launcher.py` are the primary sources of device identity and routing decisions. The bug: `.env.local` had `WINDOWS_IP=192.168.254.101` (the Mac's own IP) instead of `.108`.

Actual device map:
- `192.168.254.110` — Mac LM Studio (Mac's own LAN IP)
- `192.168.254.108` — Windows (Ollama `11434`, LM Studio `1234`)
- `127.0.0.1` — localhost for all local services

---

## Fix

```python
# orchestrator/agent_launcher.py
import socket
from urllib.parse import urlparse

def _get_local_ips() -> set[str]:
    ips = set()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("8.8.8.8", 80))
            ips.add(s.getsockname()[0])
        except OSError:
            pass
    ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    return ips

# After probing: zero out Windows endpoint if it resolves to local IP
local_ips = _get_local_ips()
if urlparse(REMOTE_WINDOWS_URL).hostname in local_ips:
    windows_ok = False
```

---

## Rules

1. **Always call `_get_local_ips()` before trusting any "remote" endpoint**
2. **One role per physical device** — zero out probes whose host IP is in local_ips
3. **On same device: Ollama > LM Studio** deterministically
4. **Crash recovery ≥ 30 seconds** — GPU model cycles need this buffer
5. **Classify errors**: 503=loading, 404=unloaded, ConnectError=offline
6. **Show progress bar** during recovery — `asyncio.sleep(N)` is invisible

---

## Commit
- `8af62f5` (PT) — feat(routing): one-role-per-device guard + GPU crash recovery cooldown

## Related

- [Session log 2026-04-07](../LESSONS.md#2026-04-07--claude--device-identity--gpu-crash-recovery)
- [UTS/03](https://github.com/diazMelgarejo/orama-system/blob/main/docs/wiki/03-device-identity.md) — full code examples
