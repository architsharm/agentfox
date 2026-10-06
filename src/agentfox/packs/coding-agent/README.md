# coding-agent

Rules for coding agents governed through their hooks, written against canonical tool
names (`shell`, `web.fetch`, `file.write`), so they hold whichever harness is attached.
`agentfox init` binds it only to agents a coding harness in the repository runs.

**Risk.** A fetched page or a command's output carries an instruction or a secret into
the agent; personal data leaves a developer's machine in a tool call.

**What it ships.** `policies/coding-agent.yaml` (5 rules, observe), golden cases.

```bash
agentfox policy packs test coding-agent
```
