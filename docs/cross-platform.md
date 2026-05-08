# Cross-Platform Compatibility — Perpetua-Tools

> **Status:** v0.9.9.8 — macOS (primary), Linux (supported)
>
> **Last updated:** 2026-05-08
>
> **Related:** [orama-system cross-platform](../../../orama-system/docs/cross-platform.md)

---

## Overview

Perpetua-Tools provides the hardware detection layer (`scripts/mac_probe.sh`) and the
orchestration supervisor (`orchestrator/supervisor.py`) used by orama-system's LAN stack.
Both must run correctly on macOS (Apple Silicon + Intel) and Linux (x86_64 + aarch64 / ARM SBC).

---

## Platform support matrix

| Feature | macOS | Linux | Windows |
|---------|-------|-------|---------|
| `scripts/mac_probe.sh` | ✅ primary | ✅ supported | ❌ not applicable |
| `orchestrator/supervisor.py` | ✅ | ✅ | ⚠ partial (no `signal.SIGTERM`) |
| `lan_discovery.py` | ✅ `ipconfig getifaddr en0` | ✅ `ip route get 8.8.8.8` | ⚠ not tested |
| `model_hardware_policy.yml` | ✅ | ✅ | ✅ (policy file is portable YAML) |
| `setup_macos.py` | ✅ runs | ⏭ skipped (Darwin guard in caller) | ⏭ not applicable |

---

## `mac_probe.sh` — cross-platform hardware detection

Called by `orchestrator/supervisor.py → detect_hardware()`. Returns JSON to stdout.
Zero external dependencies beyond bash 3.2+ builtins and OS-native tools.

### RAM detection

| OS | Source | Unit |
|----|--------|------|
| macOS | `sysctl -n hw.memsize` | bytes |
| Linux | `grep '^MemTotal:' /proc/meminfo` | **kB** (÷ 1024 ÷ 1024 for GiB) |

**Critical rule:** `/proc/meminfo` is in **kibibytes**, not bytes. The division chain
`RAM_KB / 1024 / 1024` is intentional — using `/proc/meminfo` ÷ 1e9 gives a ~7% error.

```bash
if [ "$_OS" = "Darwin" ]; then
    RAM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo "0")
    RAM_GB=$(( RAM_BYTES / 1024 / 1024 / 1024 ))
elif [ -f /proc/meminfo ]; then
    RAM_KB=$(grep '^MemTotal:' /proc/meminfo | awk '{print $2}' || echo "0")
    RAM_GB=$(( RAM_KB / 1024 / 1024 ))
fi
```

### Model / hardware ID

| OS | Source | Notes |
|----|--------|-------|
| macOS | `sysctl -n hw.model` | e.g. `Mac14,9` |
| Linux (x86 bare metal) | `/sys/devices/virtual/dmi/id/product_name` | e.g. `ThinkPad_X1_Carbon` |
| Linux (ARM SBC / Raspberry Pi) | `/proc/device-tree/model` | needs `tr -d '\0'` (null-terminated) |
| Linux (VM / container) | falls through to `linux-unknown` | no DMI in many VMs |

```bash
elif [ -f /sys/devices/virtual/dmi/id/product_name ]; then
    MODEL_ID=$(cat /sys/devices/virtual/dmi/id/product_name 2>/dev/null | tr ' ' '_')
elif [ -f /proc/device-tree/model ]; then
    MODEL_ID=$(tr -d '\0' < /proc/device-tree/model 2>/dev/null | tr ' ' '_')
```

**Rule:** always strip null bytes from `/proc/device-tree/model` — the file is null-terminated
and embedding `\0` in a JSON string value corrupts downstream parsers.

### GPU core detection

| OS / Hardware | Tool | Value |
|---------------|------|-------|
| macOS Apple Silicon | `system_profiler SPDisplaysDataType` | "Total Number of Cores" |
| macOS Intel | `system_profiler SPHardwareDataType` | fallback for Intel GPU count |
| Linux + NVIDIA | `nvidia-smi --query-gpu=multiprocessor_count` | SM count (≈ shader multiprocessors, not raw CUDA cores) |
| Linux + any GPU | `lspci \| grep -ciE 'VGA\|3D\|Display'` | device count (approximate) |
| Container / headless | falls through to `GPU_CORES=0` | graceful default |

**Note on NVIDIA SM count:** `nvidia-smi --query-gpu=multiprocessor_count` returns
**streaming multiprocessor (SM) count**, not raw CUDA core count. Multiply by
64–128 (Ampere/Ada) to get CUDA cores. The supervisor uses SM count for tier
comparison only, so this is intentional and documented.

### Private LAN IP detection

| OS | Command | Notes |
|----|---------|-------|
| macOS | `ipconfig getifaddr en0` → `en1` fallback | macOS `ipconfig` — NOT the same binary as Linux `ipconfig` |
| Linux (iproute2) | `ip route get 8.8.8.8` + awk `src` field | canonical; available on all modern distros |
| Linux (no iproute2) | `hostname -I \| awk '{print $1}'` | may return loopback on minimal containers |

**Critical rule:** `ipconfig` on Linux is a different binary from macOS `ipconfig`. Calling
`ipconfig getifaddr en0` on Linux either errors or returns the wrong result. Always branch on
`$_OS = "Darwin"` before using macOS `ipconfig`.

```bash
if [ "$_OS" = "Darwin" ]; then
    PRIVATE_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "0.0.0.0")
elif command -v ip &>/dev/null; then
    PRIVATE_IP=$(ip route get 8.8.8.8 2>/dev/null | awk '/src/{for(i=1;i<=NF;i++) if($i=="src") {print $(i+1); exit}}')
elif command -v hostname &>/dev/null; then
    PRIVATE_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "0.0.0.0")
fi
```

### AI tier + Ollama parallelism mapping

These are computed purely from `$RAM_GB` and are OS-independent:

| RAM | AI Tier | Ollama parallel |
|-----|---------|-----------------|
| ≥ 32 GB | `ultra` — 27B+ models, multi-agent, 32k+ context | 4 |
| ≥ 16 GB | `standard` — 13B–14B, 8-bit quant | 2 |
| < 16 GB | `base` — 7B–8B, 4-bit quant only | 1 |

### Reference JSON output (Mac14,9 / Apple Silicon M2 Pro, 16 GB)

```json
{
  "model_id": "Mac14,9",
  "ram_gb": 16,
  "gpu_cores": 16,
  "private_ip": "10.179.147.43",
  "arch": "arm64",
  "os": "Darwin",
  "is_apple_silicon": true,
  "ai_tier": "standard",
  "ollama_recommended_parallel": 2
}
```

---

## `orchestrator/supervisor.py` — cross-platform notes

### `detect_hardware()` call chain

```
supervisor.py → subprocess.run(["bash", "scripts/mac_probe.sh"])
             → parse stdout JSON
             → populate HardwareSpec dataclass
```

The `bash` invocation is portable: bash 3.2 (macOS default since 10.3) and bash 4+ (Linux).
`mac_probe.sh` handles the OS branching internally — the caller is OS-blind.

### Signal handling

`supervisor.py` uses `signal.SIGTERM` for graceful shutdown, which works on macOS and Linux.
Windows does not support `SIGTERM` natively — `os.kill(pid, signal.SIGTERM)` maps to
`TerminateProcess()` (hard kill). A Windows-safe version would use `subprocess.Popen.terminate()`
or `taskkill /F /PID`. Deferred to v2 (Windows supervisor support is out of scope for v0.9.x).

### File paths

The supervisor uses `os.path.join` throughout — no hardcoded `/` separators. All temp files
write to the repo's `.logs/` directory. On Windows, `.logs/` would work but the `lsof`-based
port detection in `portal_server.py` (orama-layer) would need the `netstat -ano` fallback
(already implemented in orama's portal as of v0.9.9.8).

---

## `lan_discovery.py` — cross-platform IP resolution

LAN discovery resolves the host's non-loopback IP as the "bind address" for orama's services.

| Platform | Primary method | Fallback |
|----------|---------------|---------|
| macOS | `ipconfig getifaddr en0` | `en1`, then `0.0.0.0` |
| Linux | `ip route get 8.8.8.8` src field | `hostname -I` first token |
| Windows | `socket.gethostbyname(socket.gethostname())` | `0.0.0.0` |

**Rule:** never bind to `127.0.0.1` for LAN-visible services — other devices on the LAN
(e.g. the Windows node at `.108`) cannot reach a loopback-bound server on the Mac at `.110`.

---

## Known Linux-only assumptions / gotchas

| File | Assumption | Impact | Status |
|------|------------|--------|--------|
| `scripts/mac_probe.sh` | `sysctl -n hw.memsize` | Silent `0` on Linux | Fixed v0.9.9.8 |
| `scripts/mac_probe.sh` | `system_profiler` | `command not found` on Linux | Fixed v0.9.9.8 |
| `scripts/mac_probe.sh` | `ipconfig getifaddr en0` | Wrong binary on Linux | Fixed v0.9.9.8 |
| `orchestrator/supervisor.py` | `signal.SIGTERM` | Hard-kill on Windows (acceptable) | Known, deferred |
| `setup_macos.py` caller | Unconditional invocation | `FileNotFoundError` on Linux | Fixed v0.9.9.8 (Darwin guard in `start.sh`) |

---

## Testing cross-platform probes

### Verify `mac_probe.sh` locally

```bash
# macOS (should return Darwin fields)
bash scripts/mac_probe.sh | python3 -m json.tool

# Linux (docker) — minimal Ubuntu image
docker run --rm -v "$(pwd)/scripts:/scripts" ubuntu:22.04 bash /scripts/mac_probe.sh | python3 -m json.tool

# Alpine (no lsof, no nc, no nvidia-smi)
docker run --rm -v "$(pwd)/scripts:/scripts" alpine:3.19 sh -c "apk add --no-cache bash > /dev/null 2>&1 && bash /scripts/mac_probe.sh"
```

Expected on Alpine (minimal): `ram_gb` from `/proc/meminfo`, `gpu_cores: 0`, `private_ip` from
`hostname -I`, `model_id: linux-unknown`.

### Verify supervisor hardware detection

```python
# From orama-system's PT-calling code
import subprocess, json
result = subprocess.run(["bash", "scripts/mac_probe.sh"], capture_output=True, text=True, cwd="/path/to/Perpetua-Tools")
hw = json.loads(result.stdout)
assert hw["ram_gb"] > 0, "RAM detection failed"
assert hw["os"] in ("Darwin", "Linux"), "Unexpected OS value"
```

---

## Adding a new platform

When extending hardware detection to a new OS (e.g., FreeBSD, Windows WSL2):

- [ ] Check `/proc/meminfo` vs `sysctl hw.memsize` vs `wmic` for RAM
- [ ] Check DMI path vs `/proc/device-tree/model` vs `systeminfo` for model ID
- [ ] Verify `ip route` or equivalent for non-loopback LAN IP
- [ ] Test `bash scripts/mac_probe.sh` and confirm JSON output is valid (no null bytes, no empty strings)
- [ ] Update the support matrix at the top of this file
- [ ] Update `orchestrator/supervisor.py` if `detect_hardware()` needs OS-specific handling
- [ ] Add a validation entry in the LESSONS.md section for that platform
