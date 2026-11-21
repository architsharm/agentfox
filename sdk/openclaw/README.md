# AgentFox for OpenClaw

An [OpenClaw](https://github.com/openclaw/openclaw) plugin that checks every tool call an
OpenClaw agent makes against [AgentFox](https://useagentfox.com) before it runs. Shell
commands, browser actions, file writes and the messages it sends on WhatsApp, Slack or
Teams are allowed, blocked with a reason, or held for an approver.

It is for a team sharing one OpenClaw inside one trust boundary. It does not make OpenClaw
safe to share between people who do not trust each other: OpenClaw's own SECURITY.md says
one gateway should not be shared that way, and a plugin cannot change that.

## What it does

- **Before each tool call** (`before_tool_call`), it asks the AgentFox gateway
  (`POST /v1/guard/tool_call`) and applies the answer:
  - allowed: the call runs;
  - blocked: OpenClaw gets the rule's reason instead of running it;
  - held: by default the call is refused with a link, an approver decides in AgentFox, and
    the same call retried runs once. With `approvals: "openclaw"` it uses OpenClaw's own
    approval prompt instead, which the person chatting can answer.
- **After each tool call** (`after_tool_call`), it keeps the session's recent tool results,
  so AgentFox can tell when an argument was copied out of a web page or a file rather than
  typed by the user. That is what holds "send the invoices to the address on this page".
- If AgentFox cannot be reached it fails closed (the call does not run) unless you set
  `failMode: "open"`.

Gated on the applied verdict: a rule in Watch mode records what it would have done and
lets the call run.

## Set up

The quickest way is the kit in `deploy/openclaw/` of the AgentFox repository: one command
starts AgentFox and OpenClaw together with this plugin loaded. To add it to an OpenClaw you
already run:

1. Build it: `npm ci && npm run build` in this directory.
2. Point OpenClaw at it in `openclaw.json`:

   ```json
   {
     "plugins": {
       "load": { "paths": ["/path/to/sdk/openclaw"] },
       "entries": {
         "agentfox": {
           "enabled": true,
           "config": { "baseUrl": "http://localhost:8080", "apiKey": "nom_agt_…" }
         }
       }
     }
   }
   ```

3. Tell AgentFox what OpenClaw's tools do and grant them to the agent:
   `deploy/openclaw/agentfox-setup.sh openclaw` (add `--block` to hold untrusted calls
   right away instead of watching first).

Optional, and recommended: also use AgentFox as OpenClaw's model endpoint (an
OpenAI-compatible provider with `baseUrl` set to the gateway's `/v1`). AgentFox then checks
what reaches the model too, and holds the real model key so the team never sees it.

## Settings

| Key | Default | |
|---|---|---|
| `baseUrl` | (required) | The AgentFox gateway |
| `apiKey` | none | An AgentFox agent key; without one calls are recorded as unregistered traffic |
| `agent` | `openclaw` | The agent's slug in AgentFox (`openclaw-<id>` for a named OpenClaw agent) |
| `failMode` | `closed` | `closed` blocks a call AgentFox cannot check; `open` runs it |
| `approvals` | `agentfox` | `agentfox`: an approver decides in AgentFox; `openclaw`: OpenClaw's prompt |
| `timeoutMs` | `10000` | OpenClaw allows a `before_tool_call` hook 15 seconds |
| `resultsKept` | `20` | Tool results remembered per session for provenance |

## What it does not cover

- Code a skill or plugin runs itself, outside a tool call, and commands a skill starts
  inside a shell call that was already allowed.
- What OpenClaw does without a tool call (channel delivery of the model's own reply,
  scheduled heartbeats): use AgentFox as the model endpoint to see those turns.
- A held call in a run nobody is watching (a cron job) is refused; it is not queued.
- In Block, a browser step or a file write whose arguments came from a fetched page is
  held, which can be noisy for research-heavy agents. Watch it on your traffic first.

## Develop

`npm test` runs the decision logic against a stand-in gateway; `npm run typecheck` checks
types against the slice of OpenClaw's plugin SDK declared in `src/openclaw.d.ts`.
