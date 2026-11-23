#!/bin/sh
# Teach AgentFox what Hermes Agent's built-in tools can do, and grant them to the agent.
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

AGENT="hermes"
BLOCK=0
for arg in "$@"; do
  case "$arg" in
    --block) BLOCK=1 ;;
    -*) echo "unknown option: $arg" >&2; exit 2 ;;
    *) AGENT="$arg" ;;
  esac
done

# Register the agent first: grants need it to exist, and on a fresh install it would
# otherwise appear only on Hermes's first tool call.
agentfox agents register "$AGENT" --name "Hermes Agent" >/dev/null

declare_tool() { agentfox declare tool "$1" --impact "$2" ${3:+--effect "$3"} >/dev/null; }

# Impact is the axis containment reasons over. Reads stay reads; tools that act on the
# world are high impact, so an argument copied out of untrusted content holds them.
# The lists cover Hermes Agent's core toolsets (toolsets.py) as of November 2026.
READS="web_search web_extract x_search read_file search_files vision_analyze video_analyze
  skills_list skill_view session_search clarify kanban_show kanban_list kanban_attachments
  feishu_doc_read"
WRITES="write_file patch todo_list memory image_generate video_generate text_to_speech
  kanban_complete kanban_block kanban_request_review kanban_request_changes kanban_heartbeat
  kanban_comment kanban_create kanban_link kanban_unblock kanban_attach kanban_attach_url"
# Run commands or drive a browser or desktop: free with what the user typed, held when an
# argument came from a page, a file or another tool's output.
ACTS="terminal process_manage execute_code browser_exec browser_cdp browser_dialog computer_use"
SENDS="send_message"
# Change Hermes itself, start more agents, use stored logins, or act while nobody is watching.
APPROVE="cronjob_manage delegate_task skill_manage browser_vault manage_connections discord_admin"

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

# Least privilege: the agent may use these tools. Anything else Hermes adds later is
# ungranted until someone grants it (recorded in Watch, refused in Block).
for t in $READS $WRITES; do grant "$t"; done
for t in $ACTS $SENDS; do grant "$t" --max-taint user; done
for t in $APPROVE; do grant "$t" --requires-approval; done

if [ "$BLOCK" = 1 ]; then
  agentfox policy enforce tool-containment >/dev/null
  echo "AgentFox: Hermes tools declared and granted to '$AGENT'. Tool containment is in Block."
else
  echo "AgentFox: Hermes tools declared and granted to '$AGENT'. Tool containment is in Watch;"
  echo "          switch it to Block with: agentfox policy enforce tool-containment"
fi
