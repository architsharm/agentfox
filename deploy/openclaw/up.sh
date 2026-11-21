#!/bin/sh
# Start OpenClaw behind AgentFox: AgentFox first, then its tool setup, then OpenClaw.
#
#   deploy/openclaw/up.sh [--block] [owner-email]
#
# --block switches Tool containment to Block (see agentfox-setup.sh); without it,
# AgentFox watches first. Run from anywhere; paths are resolved from this file.
set -eu

KIT="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$KIT/../.." && pwd)"
ENV_FILE="$KIT/.env"
BLOCK=""
OWNER="owner@example.com"
for arg in "$@"; do
  case "$arg" in
    --block) BLOCK="--block" ;;
    -*) echo "unknown option: $arg" >&2; exit 2 ;;
    *) OWNER="$arg" ;;
  esac
done

if [ ! -f "$ENV_FILE" ]; then
  echo "No $ENV_FILE yet. Copy the example and fill it in:" >&2
  echo "  cp $KIT/.env.example $ENV_FILE" >&2
  exit 1
fi

dc() { docker compose --env-file "$ENV_FILE" -f "$ROOT/deploy/docker-compose.yml" -f "$KIT/compose.yml" "$@"; }

echo "1/4 Starting AgentFox (database, gateway, dashboard)..."
dc up -d db gateway dashboard

printf "2/4 Waiting for the gateway"
i=0
until dc exec -T gateway agentfox --help >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -gt 60 ]; then echo; echo "The gateway did not come up; see: docker compose logs gateway" >&2; exit 1; fi
  printf "."; sleep 2
done
echo

echo "3/4 Declaring OpenClaw's tools and granting them to the openclaw agent..."
dc exec -T gateway sh /kit/agentfox-setup.sh openclaw $BLOCK
if dc exec -T gateway agentfox admin users create "$OWNER" --role owner --token 2>/dev/null; then
  echo "    Sign in to AgentFox at http://localhost:3000/login with the token above."
fi

echo "4/4 Building the plugin and starting OpenClaw..."
dc up -d openclaw

cat <<EOF

Done.
  OpenClaw    http://localhost:18789   (token: OPENCLAW_GATEWAY_TOKEN in $ENV_FILE)
  AgentFox    http://localhost:3000    (Activity shows every tool call; Approvals, the held ones)

Every tool call OpenClaw makes is now checked by AgentFox first.
EOF
