#!/bin/sh
# The gateway's start command in deploy/openclaw/render.yaml. Creates the schema, then
# runs agentfox-setup.sh (declares OpenClaw's tools and grants them to the `openclaw`
# agent) in the background so the port opens at once. Safe on every boot: init_db and
# the setup script are both idempotent.
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
python -c "from agentfox.core.db import init_db; init_db()"
(sh "$DIR/agentfox-setup.sh" openclaw || echo "agentfox-setup.sh failed; run it again from this service's Shell tab: sh $DIR/agentfox-setup.sh openclaw" >&2) &
exec uvicorn agentfox.apps.gateway.app:app --host 0.0.0.0 --port 8080
