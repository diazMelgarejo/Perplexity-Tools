---
name: agent-run
description: Launch a Perpetua-Tools agent with LM Studio endpoint validation and env setup
disable-model-invocation: true
---

**1. Verify .env.lmstudio exists:**
```bash
[[ -f .env.lmstudio ]] || python3 ~/.openclaw/scripts/discover.py --force
cat .env.lmstudio | grep LM_STUDIO
```

**2. Validate Win endpoint:**
```bash
source .env.lmstudio 2>/dev/null || true
curl -s --connect-timeout 3 "$LM_STUDIO_WIN_ENDPOINTS/v1/models" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d['data']), 'models on Win')"
```
If curl fails → `python3 ~/.openclaw/scripts/discover.py --force` then retry once.

**3. Launch:**
```bash
set -a && source .env && source .env.lmstudio && set +a
python agent_launcher.py "$@"
```
