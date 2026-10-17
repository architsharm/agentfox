# coding-agent

Rules for coding agents governed through their hooks, written against canonical tool
names (`shell`, `web.fetch`, `file.write`), so they hold whichever harness is attached.
`agentfox init` binds it only to agents a coding harness in the repository runs.

**Risk.** A fetched page or a command's output carries an instruction or a secret into
the agent; personal data leaves a developer's machine in a tool call.

**What it ships.** `policies/coding-agent.yaml` (10 rules, observe), golden cases. Five of
the rules act on a command blocklist ported from a Claude Code governance plugin (MIT;
see `capabilities/detection/shell_blocklist.py`): recursive forced deletes outside build
artefacts, downloads piped into a shell, cloud metadata endpoints, credential-file reads
and environment dumps, and read tools pointed at credential paths.

```bash
agentfox policy packs test coding-agent
```
