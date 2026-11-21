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

# Impact is the axis containment reasons over. Reads stay reads; tools that act on the
# world are high impact, so an argument copied out of untrusted content holds them.
# `message` is high impact, not irreversible: irreversible would hold every send.
# The lists cover OpenClaw 2026.11 and keep older names (cron, image, web_search).
READS="read ls dir_list dir_fetch file_fetch pdf web_fetch web_search image view_image
  session_status sessions_list sessions_history sessions_search agents_list agents_wait
  conversations_list get_goal github_identity_status github_read github_search memory_get
  memory_search skills_read skills_search transcripts intent progress_card presence
  ask_user node_inference"
WRITES="write edit apply_patch file_write create_goal update_goal canvas dashboard theme
  portal mobile_ui image_generate music_generate video_generate tts talk_voice sessions
  sessions_yield"
# Run commands or reach people: free with what the user typed, held when an argument
# came from a page, a file or another tool's output.
ACTS="exec process terminal nodes browser github_publish"
SENDS="message conversations_send conversations_turn sessions_send"
# Change OpenClaw itself, start more agents, or act while nobody is watching.
APPROVE="cron automations gateway plugins secrets skill_workshop openclaw sessions_spawn
  sessions_create subagents"

for t in $READS; do declare_tool "$t" read; done
for t in $WRITES; do declare_tool "$t" write; done
for t in $ACTS $APPROVE; do declare_tool "$t" high_impact; done
for t in $SENDS; do declare_tool "$t" high_impact communication; done

# Grant once: `permit grant` adds a new grant each time, so skip a tool that has one.
GRANTED="$(agentfox permit list "$AGENT" 2>/dev/null || true)"
grant() {
  tool="$1"; shift
  if printf '%s\n' "$GRANTED" | grep -Eq "cap_[a-z0-9]+ +$tool( |\$)"; then return 0; fi
  agentfox permit grant "$AGENT" "$tool" "$@" --yes >/dev/null
}

# Least privilege: the agent may use these tools. Anything else OpenClaw adds later is
# ungranted until someone grants it (recorded in Watch, refused in Block).
for t in $READS $WRITES; do grant "$t"; done
for t in $ACTS $SENDS; do grant "$t" --max-taint user; done
for t in $APPROVE; do grant "$t" --requires-approval; done

if [ "$BLOCK" = 1 ]; then
  agentfox policy enforce tool-containment >/dev/null
  echo "AgentFox: OpenClaw tools declared and granted to '$AGENT'. Tool containment is in Block."
else
  echo "AgentFox: OpenClaw tools declared and granted to '$AGENT'. Tool containment is in Watch;"
  echo "          switch it to Block with: agentfox policy enforce tool-containment"
fi
