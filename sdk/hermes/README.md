# AgentFox for Hermes Agent

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin that checks every
tool call Hermes makes against [AgentFox](https://useagentfox.com) before it runs. Terminal
commands, code execution, browser and desktop control, file writes and the messages it
sends are allowed, blocked with a reason, or held for an approver.

This is an independent integration. It is not made or endorsed by Nous Research.

## What it does

- **Before each tool call** (`pre_tool_call`), it asks the AgentFox gateway
  (`POST /v1/guard/tool_call`, through the `agentfox` Python package) and applies the answer:
  - allowed: the call runs;
  - blocked: Hermes gets the rule's reason instead of running it;
  - held: by default the call is refused with a link, an approver decides in AgentFox, and
    the same call retried runs once. With `AGENTFOX_APPROVALS=hermes` it goes to Hermes's
    own approval gate instead, which the person chatting can answer.
- **After each tool call** (`post_tool_call`), it keeps the conversation's recent tool
  results, so AgentFox can tell when an argument was copied out of a web page or a file
  rather than typed by the user.
- If AgentFox cannot be reached it fails closed (the call does not run) unless
  `AGENTFOX_FAIL_MODE=open`. Hermes itself also fails closed if the hook errors or times out.

Gated on the applied verdict: a rule in Watch mode records what it would have done and
lets the call run.

## Set up

The quickest way is the kit in `deploy/hermes/` of the AgentFox repository: one command
starts AgentFox and builds Hermes with this plugin loaded. To add it to a Hermes you
already run:

1. Install the dependency into Hermes's Python environment: `pip install agentfox`.
2. Copy or link this directory to `~/.hermes/plugins/agentfox/` and enable it:

   ```yaml
   # ~/.hermes/config.yaml
   plugins:
     enabled:
       - agentfox
   ```

3. Set `AGENTFOX_URL` (and `AGENTFOX_AGENT_KEY`) in `~/.hermes/.env`.
4. Tell AgentFox what Hermes's tools do and grant them to the agent:
   `deploy/hermes/agentfox-setup.sh hermes` (add `--block` to hold untrusted calls right
   away instead of watching first).

Optional, and recommended: also use AgentFox as Hermes's model endpoint, a `providers:`
entry with `api` set to the gateway's `/v1` and the headers `X-AgentFox-Agent: hermes` and
`X-AgentFox-Tool-Hook: 1` in `extra_headers`. AgentFox then checks what reaches the model
too and holds the real model key. `deploy/hermes/config.yaml` does this.

## Settings

| Variable | Default | |
|---|---|---|
| `AGENTFOX_URL` | (required) | The AgentFox gateway |
| `AGENTFOX_AGENT_KEY` | none | An AgentFox agent key; without one calls are recorded as unregistered traffic |
| `AGENTFOX_AGENT` | `hermes` | The agent's slug in AgentFox |
| `AGENTFOX_FAIL_MODE` | `closed` | `closed` blocks a call AgentFox cannot check; `open` runs it |
| `AGENTFOX_APPROVALS` | `agentfox` | `agentfox`: an approver decides in AgentFox; `hermes`: Hermes's approval gate |
| `AGENTFOX_TIMEOUT` | `10` | Seconds; Hermes allows a `pre_tool_call` hook 30 by default |

## What it does not cover

- Code a skill or plugin runs itself, outside a tool call, and what a terminal command
  starts after it was allowed.
- A held call in a run nobody is watching (a cron job) is refused; it is not queued.
- In Block, a browser step or file write whose arguments came from a fetched page is held,
  which can be noisy for research-heavy agents. Watch it on your traffic first.

## Develop

`pytest tests/frameworks/test_hermes_plugin.py` (from the repository root) runs the
decision logic against a stand-in gateway.
