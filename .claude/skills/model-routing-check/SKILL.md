---
name: model-routing-check
description: Verify LM Studio endpoint reachability and routing table validity before any agent dispatch
user-invocable: false
---

Before dispatching any agent:

1. Check Mac: `curl -s --connect-timeout 3 http://localhost:1234/v1/models | python3 -c "import sys,json; print('Mac OK:', len(json.load(sys.stdin)['data']), 'models')"`
2. Check Win: `curl -s --connect-timeout 3 "$LM_STUDIO_WIN_ENDPOINTS/v1/models" | python3 -c "import sys,json; print('Win OK:', len(json.load(sys.stdin)['data']), 'models')"`
3. Cross-check config/routing.yml task_types against config/models.yml role assignments
4. If either endpoint is down: log warning, continue with available endpoint only. Do NOT abort.
5. Report: which endpoints are live, which task_types are fully routable
