# Perplexity-Tools v0.9.0.0 — Hybrid Multi-Agent Orchestration

**Status**: Production-ready (March 22, 2026)  
**Budget**: < $5/month (98% local, 2% strategic cloud)  
**Hardware**: MacBook Pro M2 16GB + Dell Precision 3660 RTX 3080 10GB

## Overview

Top-level orchestrator for multi-agent systems. Integrates:
- **Perplexity API** for strategic reasoning (Claude Sonnet 4.5, Grok 4.1)
- **Local Ollama/MLX** for 98% of compute (Qwen3 models)
- **CrewAI v1.9.0** for agent coordination
- **Redis** for state persistence & idempotency
- Compatible with [ultrathink-system](https://github.com/diazMelgarejo/ultrathink-system) and ECC-tools

## Quick Start

```bash
# 1. Clone
git clone -b v0.9.0.0 https://github.com/diazMelgarejo/Perplexity-Tools.git
cd Perplexity-Tools

# 2. Install models (see SKILL.md)
ollama pull qwen3:8b-instruct
ollama pull qwen3-coder:14b
ollama pull qwen3:30b-a3b-instruct-q4_K_M  # KEY: Critic + Fallback

# 3. Install Python deps
pip install -r requirements.txt

# 4. Configure
cp .env.example .env
# Edit: PERPLEXITY_API_KEY, REDIS_HOST

# 5. Run
python orchestrator.py
```

## Architecture

```
Query → Router
    ├─ Privacy critical? → Local only
    ├─ Budget exceeded? → Fallback to Qwen3-30B (local)
    ├─ Real-time data needed? → Perplexity (Grok 4.1)
    ├─ Strategic reasoning? → Perplexity (Claude Sonnet 4.5)
    └─ Default → Local Qwen3 (8B or 14B)
        ↓
    Batch Execution (Mac + Dell in parallel)
        ↓
    Critic Pass (Qwen3-30B reviews quality)
        ↓
    Synthesis (Final answer)
```

## Key Features

### 1. Intelligent Fallback Chain
- **Cloud unreachable?** → Auto-fallback to Qwen3-30B (Dell)
- **Budget exhausted?** → Hard cutoff, use local only
- **Offline operation**: Full functionality without internet

### 2. Cost Guard (< $5/month)
```python
MAX_DAILY_SPEND = $0.17  # ~$5/30 days
MAX_DAILY_CALLS = 5
# Perplexity pricing:
#   Claude Sonnet 4.5: ~$0.05/call
#   Grok 4.1 Thinking: ~$0.03/call
```

### 3. Qwen3-30B as Universal Fallback
- **Orchestration**: Decomposes tasks when Claude unavailable
- **Critic**: Reviews batch outputs (quality score 1-10)
- **Refiner**: Improves sub-agent results
- **Offline reasoning**: 200+ step chains locally

### 4. Idempotent Orchestrator
- Checks Redis for running agents before spawning
- Reuses existing instances
- Asks user on conflicts
- Auto-destroys on completion

## File Structure

```
Perplexity-Tools/
├─ SKILL.md                    # Model selection logic (READ FIRST)
├─ orchestrator.py             # Main orchestration engine
├─ requirements.txt            # Python dependencies
├─ .env.example                # Config template
├─ examples/
│  ├─ workflow_local.py        # 100% local example
│  ├─ workflow_strategic.py    # Cloud + local example
│  └─ workflow_realtime.py     # Finance/real-time research
└─ docs/
   ├─ INSTALLATION.md          # Detailed setup
   ├─ INTEROP.md               # ultrathink/ECC integration
   └─ TROUBLESHOOTING.md       # Common issues
```

## Hardware Profiles

### Mac M2 16GB (Profile A)
- **Primary**: `qwen3:8b-instruct` (standard tasks, 60% load)
- **Fast**: `qwen3:4b-instruct` (autocomplete, quick queries)
- **Embeddings**: `bge-m3` (72% accuracy)

### Dell RTX 3080 10GB (Profile B)
- **Coding**: `qwen3-coder:14b` (heavy generation, 35% load)
- **Critic**: `qwen3:30b-a3b-instruct-q4_K_M` (refinement, 3% load)
- **Reranker**: `qwen3-reranker-4b` (search optimization, 2% load)

## API Endpoints

```python
# Main orchestration
POST /orchestrate
{
  "description": "Task description",
  "is_finance_realtime": false,  # true = Grok 4.1
  "enable_critic": true           # true = Qwen3-30B review
}

# Status check
GET /status
# Returns: calls_today, spend_today, fallbacks_today

# Health check
GET /health
```

## Integration with Other Repos

### ultrathink-system (v0.9.4.0)
```python
# Call ultrathink for deep reasoning
import httpx

response = httpx.post(
    "http://localhost:8001/ultrathink",
    json={"query": "Analyze quantum error correction", "mode": "deep"}
)
```

### ECC-tools (sub-agent selection)
- Sub-agents follow ECC-tools default logic
- Top-level agents follow SKILL.md first
- Seamless interoperability via shared Redis state

## Runtime Modes

| Mode | Mac | Dell | Cloud | Critic | Use Case |
|------|-----|------|-------|--------|----------|
| **mac_only** | ✓ | ✗ | ✓ | ✗ | Portable, reduced capability |
| **dell_only** | ✗ | ✓ | ✓ | ✓ | Heavy workstation tasks |
| **lan_full** | ✓ | ✓ | ✓ | ✓ | **Recommended** (full power) |
| **lm_studio_mlx** | ✓ MLX | ✓ MLX | ✓ | ✓ | Alternative to Ollama |

## Performance Benchmarks

| Task Type | Model | Hardware | Speed | Cost |
|-----------|-------|----------|-------|----- |
| Quick query | Qwen3-4B | Mac | 60-80 t/s | $0 |
| Standard task | Qwen3-8B | Mac | 35-45 t/s | $0 |
| Heavy coding | Qwen3-14B | Dell GPU | 20-30 t/s | $0 |
| Orchestration (cloud) | Claude 4.5 | Perplexity | 2-3s | $0.05 |
| Orchestration (fallback) | Qwen3-30B | Dell GPU | 3-5s | $0 |
| Real-time research | Grok 4.1 | Perplexity | 2-4s | $0.03 |

## Monthly Cost Analysis

```
Scenario: 100 hours/month development

90% Local (90h):
  Mac Qwen3-8B: $0
  Dell Qwen3-14B: $0
  Dell Qwen3-30B: $0
  Subtotal: $0

10% Cloud (10h):
  Claude Sonnet 4.5: 30 calls × $0.05 = $1.50
  Grok 4.1 Thinking: 20 calls × $0.03 = $0.60
  Subtotal: $2.10

Total: $2.10/month (58% under budget)
```

## Changelog

### v0.9.0.0 (2026-03-22)
- Initial release with complete fallback logic
- Added Qwen3-30B-A3B as critic, refiner, offline orchestrator
- Perplexity API integration (Claude Sonnet 4.5 + Grok 4.1)
- Idempotent orchestrator with Redis state persistence
- 4 runtime modes (mac-only, dell-only, lan-full, lm-studio-mlx)
- Budget guard with hard $5/month cap
- Interoperability with ultrathink-system v0.9.4.0 and ECC-tools
- Comprehensive SKILL.md model selection logic

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

AGPL-3.0 — See [LICENSE](LICENSE)

## Links

- [ultrathink-system](https://github.com/diazMelgarejo/ultrathink-system) — Deep reasoning subsystem
- [SKILL.md](SKILL.md) — Complete model selection logic
- [Perplexity API Docs](https://docs.perplexity.ai) — Cloud provider
- [CrewAI Docs](https://docs.crewai.com) — Agent framework
