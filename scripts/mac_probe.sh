#!/bin/bash
# mac_probe.sh — Outputs raw hardware primitives for the Orchestration Supervisor.
# Zero external dependencies.  Output: JSON to stdout.
# Usage:  bash scripts/mac_probe.sh
# Called by: orchestrator/supervisor.py detect_hardware()
#
# Gemini-Hardware (v1/003-Gemini-Hardware.md) pattern — adapted for our actual
# stack conventions (no sqlite, no loopback enforcement, AI tier from RAM).

set -euo pipefail

MODEL_ID=$(sysctl -n hw.model 2>/dev/null || echo "unknown")
RAM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo "0")
RAM_GB=$(( RAM_BYTES / 1024 / 1024 / 1024 ))

# Robust GPU core detection for Apple Silicon (M-series chips)
GPU_CORES=$(system_profiler SPDisplaysDataType 2>/dev/null \
    | grep "Total Number of Cores" | awk '{print $5}' | head -1)
if [ -z "$GPU_CORES" ]; then
    GPU_CORES=$(system_profiler SPHardwareDataType 2>/dev/null \
        | grep "Total Number of Cores" | awk '{print $5}' | head -1)
fi

# Dynamically resolve private LAN IP (not loopback) for cross-machine LM Studio.
# Supervisor uses this to bind Ollama to the correct interface in distributed mode.
PRIVATE_IP=$(ipconfig getifaddr en0 2>/dev/null \
    || ipconfig getifaddr en1 2>/dev/null \
    || echo "0.0.0.0")

# ── AI tier mapping based on unified memory ──────────────────────────────────
# Tier 3 (ultra):    ≥32 GB  — 27B+ models, multi-agent concurrency, 32k+ context
# Tier 2 (standard): ≥16 GB  — 13B–14B models, 8-bit quant
# Tier 1 (base):     <16 GB  — 7B–8B models, 4-bit quant only
if [ "$RAM_GB" -ge 32 ] 2>/dev/null; then
    AI_TIER="ultra"
elif [ "$RAM_GB" -ge 16 ] 2>/dev/null; then
    AI_TIER="standard"
else
    AI_TIER="base"
fi

# ── Recommended Ollama parallelism (OLLAMA_NUM_PARALLEL) ────────────────────
# 8 GB:  force 4-bit quants, 1 parallel agent
# 16 GB: 2 agents safe with 8-bit quants
# 24 GB+: 4 agents + 32k+ context windows
if [ "$RAM_GB" -ge 24 ] 2>/dev/null; then
    OLLAMA_PARALLEL=4
elif [ "$RAM_GB" -ge 16 ] 2>/dev/null; then
    OLLAMA_PARALLEL=2
else
    OLLAMA_PARALLEL=1
fi

# ── Determine if Apple Silicon (arm64) ───────────────────────────────────────
ARCH=$(uname -m 2>/dev/null || echo "unknown")
IS_APPLE_SILICON=false
if [[ "$ARCH" == "arm64" ]]; then
    IS_APPLE_SILICON=true
fi

cat <<EOF
{
  "model_id": "$MODEL_ID",
  "ram_gb": $RAM_GB,
  "gpu_cores": ${GPU_CORES:-0},
  "private_ip": "$PRIVATE_IP",
  "arch": "$ARCH",
  "is_apple_silicon": $IS_APPLE_SILICON,
  "ai_tier": "$AI_TIER",
  "ollama_recommended_parallel": $OLLAMA_PARALLEL
}
EOF
