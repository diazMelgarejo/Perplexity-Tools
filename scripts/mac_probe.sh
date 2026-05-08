#!/bin/bash
# mac_probe.sh — Outputs raw hardware primitives for the Orchestration Supervisor.
# Zero external dependencies.  Output: JSON to stdout.
# Usage:  bash scripts/mac_probe.sh
# Called by: orchestrator/supervisor.py detect_hardware()
#
# Supports: macOS (Apple Silicon + Intel), Linux (x86_64 + aarch64), CI/Docker.
# Gemini-Hardware (v1/003-Gemini-Hardware.md) pattern — cross-platform adaptation.

set -euo pipefail

_OS="$(uname -s 2>/dev/null || echo Unknown)"
ARCH="$(uname -m 2>/dev/null || echo unknown)"

# ── RAM detection (cross-platform) ───────────────────────────────────────────
RAM_BYTES=0
RAM_GB=0

if [ "$_OS" = "Darwin" ]; then
    RAM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo "0")
    RAM_GB=$(( RAM_BYTES / 1024 / 1024 / 1024 ))
elif [ -f /proc/meminfo ]; then
    # Linux: MemTotal is in kB
    RAM_KB=$(grep '^MemTotal:' /proc/meminfo | awk '{print $2}' || echo "0")
    RAM_GB=$(( RAM_KB / 1024 / 1024 ))
else
    RAM_GB=0
fi

# ── Model/hardware ID (cross-platform) ───────────────────────────────────────
MODEL_ID="unknown"
if [ "$_OS" = "Darwin" ]; then
    MODEL_ID=$(sysctl -n hw.model 2>/dev/null || echo "unknown")
elif [ -f /sys/devices/virtual/dmi/id/product_name ]; then
    MODEL_ID=$(cat /sys/devices/virtual/dmi/id/product_name 2>/dev/null | tr ' ' '_' || echo "linux-generic")
elif [ -f /proc/device-tree/model ]; then
    # Raspberry Pi / ARM SBC
    MODEL_ID=$(tr -d '\0' < /proc/device-tree/model 2>/dev/null | tr ' ' '_' || echo "arm-sbc")
else
    MODEL_ID="linux-unknown"
fi

# ── GPU core detection (cross-platform) ──────────────────────────────────────
GPU_CORES=0

if [ "$_OS" = "Darwin" ]; then
    # macOS: system_profiler for Apple Silicon GPU core count
    _GPU_TMP=$(system_profiler SPDisplaysDataType 2>/dev/null \
        | grep "Total Number of Cores" | awk '{print $5}' | head -1)
    if [ -z "$_GPU_TMP" ]; then
        _GPU_TMP=$(system_profiler SPHardwareDataType 2>/dev/null \
            | grep "Total Number of Cores" | awk '{print $5}' | head -1)
    fi
    GPU_CORES="${_GPU_TMP:-0}"
elif command -v nvidia-smi &>/dev/null; then
    # Linux + NVIDIA: report CUDA cores would need nvml; report SM count instead
    SM_COUNT=$(nvidia-smi --query-gpu=multiprocessor_count --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ' || echo "0")
    GPU_CORES="${SM_COUNT:-0}"
elif command -v lspci &>/dev/null; then
    # Linux: count GPU devices (approximate)
    GPU_COUNT=$(lspci 2>/dev/null | grep -ciE 'VGA|3D|Display' || echo "0")
    GPU_CORES="${GPU_COUNT:-0}"
fi

# ── Private LAN IP (cross-platform) ──────────────────────────────────────────
PRIVATE_IP="0.0.0.0"

if [ "$_OS" = "Darwin" ]; then
    PRIVATE_IP=$(ipconfig getifaddr en0 2>/dev/null \
        || ipconfig getifaddr en1 2>/dev/null \
        || echo "0.0.0.0")
elif command -v ip &>/dev/null; then
    # Linux iproute2: pick the source IP used to reach the default route
    PRIVATE_IP=$(ip route get 8.8.8.8 2>/dev/null | awk '/src/{for(i=1;i<=NF;i++) if($i=="src") {print $(i+1); exit}}' || echo "0.0.0.0")
elif command -v hostname &>/dev/null; then
    PRIVATE_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "0.0.0.0")
fi

# ── AI tier mapping based on unified/system memory ───────────────────────────
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

# ── Apple Silicon flag ────────────────────────────────────────────────────────
IS_APPLE_SILICON=false
if [ "$_OS" = "Darwin" ] && [ "$ARCH" = "arm64" ]; then
    IS_APPLE_SILICON=true
fi

cat <<EOF
{
  "model_id": "$MODEL_ID",
  "ram_gb": $RAM_GB,
  "gpu_cores": ${GPU_CORES:-0},
  "private_ip": "$PRIVATE_IP",
  "arch": "$ARCH",
  "os": "$_OS",
  "is_apple_silicon": $IS_APPLE_SILICON,
  "ai_tier": "$AI_TIER",
  "ollama_recommended_parallel": $OLLAMA_PARALLEL
}
EOF
