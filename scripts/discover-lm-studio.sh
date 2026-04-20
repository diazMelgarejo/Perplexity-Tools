#!/usr/bin/env bash
# scripts/discover-lm-studio.sh
# Layer B: gossip gate for LM Studio auto-discovery.
set -euo pipefail

DISCOVER_PY="$HOME/.openclaw/scripts/discover.py"
DISCOVERY_JSON="$HOME/.openclaw/state/discovery.json"
GOSSIP_TTL=300

if [[ ! -f "$DISCOVER_PY" ]]; then
  echo "⚠️  discover.py not installed. Run: python setup_macos.py" >&2
  exit 0
fi

if [[ -f "$DISCOVERY_JSON" ]]; then
  age=$(python3 -c "
import json
from datetime import datetime, timezone
try:
    d = json.load(open('$DISCOVERY_JSON'))
    ts = datetime.fromisoformat(d['timestamp'])
    print(int((datetime.now(timezone.utc) - ts).total_seconds()))
except Exception:
    print(99999)
" 2>/dev/null || echo 99999)
  if (( age < GOSSIP_TTL )); then
    exit 0
  fi
fi

exec python3 "$DISCOVER_PY" "$@"
