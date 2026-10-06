---
description: Read-only governance posture — runtime health, open findings, policy modes, stopped agents
allowed-tools: Bash(*agentfox* doctor*) Bash(*agentfox* findings*) Bash(*agentfox* policy list*) Bash(*agentfox* agents *) Bash(*agentfox* auth status*) Bash(*agentfox* proposals list*)
---
Run these read-only commands with `agentfox` (see the plugin's AGENTS.md "Running the CLI" if
it isn't on PATH):

1. `doctor --json`
2. `findings --json --limit 100`
3. `policy list`
4. `agents controls`
5. `auth status`
6. `proposals list --json`

Report in six short lines:

- runtime health, listing any `bad`/`warn` checks
- open findings by severity
- which policies enforce and which observe (remember `tool-containment` enforces by default)
- agents that are not active
- whether this deployment's auth is safe for where it runs
- change proposals waiting on a person, and any that loosen a control

End with the single most important next action and the skill that handles it. Change
nothing.
