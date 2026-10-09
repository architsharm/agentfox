#!/usr/bin/env bash
# Start a local AgentFox gateway for the demo on 127.0.0.1:8091 (PORT to change it).
#
# Every start uses a fresh SQLite database in .data/ (pass --keep to reuse the last
# one), runs `agentfox init`, and creates the owner admin@example.com, the identity the
# scripts and a local dashboard act as. Model calls go to OpenAI with your
# OPENAI_API_KEY, read from the environment and never written to disk.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
PY="$HERE/.venv/bin/python"
DATA="$HERE/.data"
PORT="${PORT:-8091}"

[ -x "$PY" ] || { echo "run ./setup.sh first" >&2; exit 1; }
: "${OPENAI_API_KEY:?export OPENAI_API_KEY first}"

mkdir -p "$DATA"
if [ "${1:-}" != "--keep" ]; then
  rm -f "$DATA"/gateway.db "$DATA"/gateway.db-wal "$DATA"/gateway.db-shm "$DATA"/agentfox.toml
fi

export PYTHONPATH="$REPO/src"
export AGENTFOX_DATABASE_URL="sqlite:///$DATA/gateway.db"
export AGENTFOX_DEFAULT_PROVIDER=openai
export AGENTFOX_ALLOW_EGRESS=true
export AGENTFOX_OPENAI_API_KEY="$OPENAI_API_KEY"
# Short, so approvals.py can watch an unanswered approval expire.
export AGENTFOX_APPROVAL_TTL_MINUTES="${APPROVAL_TTL_MINUTES:-2}"

agentfox() { "$PY" -c "from agentfox.apps.cli.main import app; app()" "$@"; }

cd "$DATA"
agentfox init --path "$DATA"
agentfox admin users create admin@example.com --role owner --name "Demo admin" || true

echo "gateway: http://127.0.0.1:$PORT  (database $DATA/gateway.db)"
exec "$PY" -m uvicorn agentfox.apps.gateway.app:app --host 127.0.0.1 --port "$PORT"
