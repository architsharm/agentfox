#!/bin/sh
# Teach AgentFox what OpenClaw's built-in tools can do, and grant them to the agent.
#
# Run it wherever the `agentfox` CLI reaches your AgentFox database: inside the gateway
# container (the kit does `docker compose exec gateway sh /kit/agentfox-setup.sh`), or on
# a machine with AGENTFOX_DATABASE_URL set. Safe to run again.
#
#   agentfox-setup.sh [agent-slug] [--block]
#
# Without --block, Tool containment stays in Watch: AgentFox records what it would have
# held and lets the call run, so you can see it on your own traffic first. Destructive
# shell commands (rm -rf ~, curl | sh, reading credential files) are blocked either way.
# With --block, a high-impact call whose arguments came from a web page, a file or another
# tool's output is held for an approver.
set -eu

AGENT="openclaw"
BLOCK=0
for arg in "$@"; do
  case "$arg" in
    --block) BLOCK=1 ;;
    -*) echo "unknown option: $arg" >&2; exit 2 ;;
    *) AGENT="$arg" ;;
  esac
done

# Register the agent first: grants need it to exist, and on a fresh install it would
# otherwise appear only on OpenClaw's first tool call.
agentfox agents register "$AGENT" --name "OpenClaw" >/dev/null

declare_tool() { agentfox declare tool "$1" --impact "$2" ${3:+--effect "$3"} >/dev/null; }

# Impact is the axis containment reasons over. Reads stay reads; the four tools that
# act on the world are high impact, so an argument copied out of untrusted content holds
# them. `message` is high impact, not irreversible: irreversible would hold every send.
for t in read web_fetch web_search image view_image session_status; do declare_tool "$t" read; done
for t in write edit apply_patch; do declare_tool "$t" write; done
for t in exec process browser; do declare_tool "$t" high_impact; done
declare_tool message high_impact communication
# Tools that change OpenClaw itself or act while nobody is watching.
for t in cron gateway sessions_spawn subagents; do declare_tool "$t" high_impact; done

# Grant once: `permit grant` adds a new grant each time, so skip a tool that has one.
GRANTED="$(agentfox permit list "$AGENT" 2>/dev/null || true)"
grant() {
  tool="$1"; shift
  if printf '%s\n' "$GRANTED" | grep -Eq "cap_[a-z0-9]+ +$tool( |\$)"; then return 0; fi
  agentfox permit grant "$AGENT" "$tool" "$@" --yes >/dev/null
}

# Least privilege: the agent may use these tools. Anything else OpenClaw adds later is
# recorded as ungranted until someone grants it.
for t in read web_fetch web_search image view_image session_status write edit apply_patch process browser; do
  grant "$t"
done
# Shell and messages run freely with what the user typed, and are held when an argument
# came from somewhere else.
grant exec --max-taint user
grant message --max-taint user
# Scheduling work, reconfiguring OpenClaw and starting more agents wait for a person.
for t in cron gateway sessions_spawn subagents; do
  grant "$t" --requires-approval
done

if [ "$BLOCK" = 1 ]; then
  agentfox policy enforce tool-containment >/dev/null
  echo "AgentFox: OpenClaw tools declared and granted to '$AGENT'. Tool containment is in Block."
else
  echo "AgentFox: OpenClaw tools declared and granted to '$AGENT'. Tool containment is in Watch;"
  echo "          switch it to Block with: agentfox policy enforce tool-containment"
fi
