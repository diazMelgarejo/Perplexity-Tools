---
name: api-validator
description: Validate Perplexity API and LM Studio API response schemas against implementation_templates.json. Flag new models and expired keys.
---

Run in order:

**1. Check LM Studio schema:**
```bash
source .env.lmstudio 2>/dev/null || true
curl -s "$LM_STUDIO_WIN_ENDPOINTS/v1/models" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert 'data' in d, 'missing data key'
print('Win models:', [m['id'] for m in d['data']])
"
```

**2. Cross-check against config/models.yml:** Flag any model from /v1/models NOT in models.yml as NEW.

**3. Check Perplexity key (if set):**
```bash
[[ -n "$PERPLEXITY_API_KEY" ]] && python3 scripts/test_perplexity.py --validate 2>&1 | tail -5
```

**4. Check implementation_templates.json:**
```bash
python3 -c "import json; t=json.load(open('implementation_templates.json')); print('Keys:', list(t.keys())[:10])"
```

Report: schema mismatches, new models available, expired/invalid keys.
