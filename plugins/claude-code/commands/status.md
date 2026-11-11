---
description: Read-only governance posture — runtime health, open findings, policy modes, stopped agents
allowed-tools: Bash(agentfox doctor) Bash(agentfox doctor *) Bash(agentfox findings) Bash(agentfox findings *) Bash(agentfox policy list) Bash(agentfox policy list *) Bash(agentfox agents controls) Bash(agentfox agents controls *) Bash(agentfox auth status) Bash(agentfox auth status *) Bash(agentfox proposals list) Bash(agentfox proposals list *)
---
Run these read-only commands with `agentfox` (see the plugin's AGENTS.md "Running the CLI" if
it isn't on PATH). The pre-approval above covers only these six read-only verbs invoked as
`agentfox`; reaching the CLI another way, such as through the launcher script, asks the user
once per call, which is the intended behaviour for a command that promises to change nothing.

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
