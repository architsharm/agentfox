# Live airline demo: OpenAI's multi-agent app, governed by AgentFox

OpenAI's open-source airline customer-service app
([openai/openai-cs-agents-demo](https://github.com/openai/openai-cs-agents-demo), MIT,
pinned at `bd7bfca`) runs live against a local AgentFox gateway. Six Agents SDK agents
(triage, FAQ, seats, flight info, booking and cancellation, refunds) hand off to each
other and call eleven tools. Their code is not changed: a two-line hook in its `main.py`
does three things through the OpenAI Agents SDK adapter
(`agentfox.frameworks.openai_agents`):

- sends every model call to the gateway's OpenAI-compatible proxy (`/v1`), so the app
  never holds an OpenAI key; the gateway does
- adds an AgentFox input and output guardrail to every agent
- adds an AgentFox tool guardrail to every function tool, as `airline.<tool>`

The hook is [`agentfox_wiring.py`](agentfox_wiring.py). The app is cloned into
`upstream/` at setup and never committed here.

## Prerequisites

- [uv](https://docs.astral.sh/uv/)
- `OPENAI_API_KEY` in your environment. One full `check.py` run costs a few cents of
  OpenAI usage (the app uses `gpt-5.2` for its agents and `gpt-4.1-mini` for its own
  guardrails) and takes under a minute.

## Run it

```bash
cd demo/live-airline
./setup.sh                              # clone the app, make .venv, add the hook
./gateway.sh                            # in a second terminal; fresh database each start
.venv/bin/python configure.py           # grant tools, protect the agent, enforce
.venv/bin/python check.py --auto-approve
```

`setup.sh` installs the app's requirements (pinned by `constraints.txt`) and AgentFox
itself in editable mode from this repository's root, so the demo runs the code in your
checkout. There is no vendored wheel.

`gateway.sh` serves on `127.0.0.1:8091` (`PORT=` to change it) with a SQLite database
in `.data/`, runs `agentfox init`, and creates the owner `admin@example.com`. It runs
development auth: the scripts act as that user through the `X-AgentFox-User` header.
`./gateway.sh --keep` reuses the last database.

`configure.py` uses the gateway's HTTP API the way the dashboard does:

| Step | Route | What it sets |
|---|---|---|
| warm-up | `POST /v1/guard/input` | one harmless check, so the gateway records agent `airline-cs` |
| access | `POST /api/agents/airline-cs/access` | lookups `read`; seat and booking changes `write`; `issue_compensation` `high_impact`, `cancel_flight` `irreversible`, both needing approval |
| protect | `POST /api/agents/airline-cs/protection` | prompt attacks and secrets at high, off-task actions on, blocked words Delta, United, American Airlines, topics to avoid (legal advice, lawsuits, medical advice), and the message users see |
| enforce | `POST /api/policies/simulate`, then `POST /api/policies/{key}/mode` | packs `agent.airline-cs` and `custom` switched from watching to enforcing; the gateway only enforces a simulated version |

## What each scenario shows

`check.py` runs these and checks governance facts (tools that ran, held calls, the
blocked message, traces and approvals on the gateway), not the model's wording. It
prints a pass/fail table and exits 1 on a failure.

| Scenario | What happens |
|---|---|
| `status` | Read tools are granted; the agent looks up the trip and answers. |
| `seat` | `update_seat` is a granted write; the change goes through. |
| `compensation` | `issue_compensation` is held for approval and does not run. |
| `competitor` | "Delta" is a blocked word: stopped, the user sees the configured message. |
| `legal` | A topic to avoid: stopped the same way. |
| `injection` | A prompt attack: stopped before the model sees it. |
| `secret` | A pasted AWS key: stopped before the model sees it. |
| `pii` | Card and SSN: the baseline pack only watches, so AgentFox lets the turn run and each trace records that enforcing would have blocked it. (The app's own LLM Jailbreak Guardrail sometimes refuses this turn; that is the app's call.) |
| `outage` | `flight_status_tool` fails (a simulated outage for flight `PA000`): the run shows a failed step. |
| `planted` | The FAQ entry for wifi carries a planted instruction (simulated): AgentFox withholds the tool result before the model reads it (`injection.indirect`). |
| `prediction` | "Will my flight be delayed?" is a prediction, outside what the agent may answer: it abstains instead of guessing (`answerability.unknowable`). |
| `offtopic` | Not checked. The app's own Relevance Guardrail refuses it; AgentFox runs beside the app's guardrails, not instead of them. |
| cancellation | `approval_flow.py`: `cancel_flight` is held, a person approves, the customer asks again and the flight is cancelled once. Asking a third time cancels nothing: an approval covers one call. |

A blocked message reaches the app as an error from whichever model call the gateway
refused first: an HTTP 403 whose body carries `user_message`, or an error event in a
streamed reply. The streamed error event does not carry `user_message` yet, so for
those `check.py` reads the message from the trace's decision.

The two simulated faults live in `agentfox_wiring.py`; `AGENTFOX_FAULTS=0` turns them
off. The app's own tools never fail or return hostile text, so without them the
failure paths would have nothing to catch.

### Every approval outcome

```bash
.venv/bin/python approvals.py          # approve, deny, changed, message, expire
```

| Case | What it checks |
|---|---|
| `approve` | Compensation is held; approved; asked again it is issued once; a third ask issues nothing; the approval ends `used`. |
| `deny` | Held, denied, never issued. |
| `changed` | An approval covers the call a person saw: presented with different arguments it is held again; with the approved ones it runs. |
| `message` | The blocked-words rule switched to "ask a person": the message is held; once approved the same message goes through once. Needs `AGENTFOX_MODEL_DIRECT=1` (through the proxy the model call carries the whole conversation, which the approval does not cover). |
| `expire` | Nobody answers. After `APPROVAL_TTL_MINUTES` (2 on `gateway.sh`) the approval expires, which denies. |

### Watching, enforcing, asking a person

```bash
.venv/bin/python modes.py
```

Runs a prompt attack and a competitor's name with the packs watching (nothing stopped,
each run records that enforcing would block), enforcing (both blocked), and with the
two rules switched to "ask a person" (both held for approval). Leaves the packs
enforcing.

### Against a hosted gateway

The hosted gateway may hold no OpenAI key, so call OpenAI directly and send only the
checks to the gateway. Create a key on the dashboard (Settings, API keys) and run:

```bash
AGENTFOX_GATEWAY=https://your-gateway AGENTFOX_API_KEY=<agent key> AGENTFOX_MODEL_DIRECT=1 .venv/bin/python run_all.py
```

Set `AGENTFOX_AGENT_KEY` to the agent's own key (the agent's Identity page) to have the agent's checks made with it rather than the operator token. Each reply then reports its tokens, so runs show their cost. With an owner's API
token the other scripts work the same way (`configure.py`, `check.py`, `modes.py`,
`approvals.py`); they change that workspace's configuration for `airline-cs` and its
custom-rules pack, so point them at a workspace meant for it.

Other ways in:

```bash
.venv/bin/python run_all.py                 # every scenario in scenarios.json, as JSON
.venv/bin/python run_all.py competitor      # one
.venv/bin/python drive.py "Can I change my seat to 12C?" "Yes"
.venv/bin/python approval_flow.py           # waits for you to approve on the dashboard
```

## Watch it in the dashboard

```bash
cd dashboard
AGENTFOX_API_URL=http://127.0.0.1:8091 npm run dev
```

Open http://localhost:3000. Agent `airline-cs` shows its traces, tool access with usage,
protection and the held approvals. Run `approval_flow.py` without `--auto-approve` and
approve the cancellation from the Approvals page.

To chat with the app's own UI instead, start its backend from the cloned folder with
`../../.venv/bin/uvicorn main:app --port 8000` in `upstream/python-backend`, and its
front end per `upstream/README.md`.

## Files

| File | What it is |
|---|---|
| `setup.sh` | Clones the app at the pinned commit, builds `.venv`, copies in the hook. |
| `patch_main.py` | Adds the two hook lines to the app's `main.py`; idempotent. |
| `agentfox_wiring.py` | The hook: gateway client, guardrails on every agent and tool. |
| `gateway.sh` | Starts the local gateway with a fresh database. |
| `configure.py` | The customer configuration, through the HTTP API. |
| `drive.py` | Runs a conversation the way the app's chat endpoint streams it. |
| `scenarios.json`, `run_all.py` | The scripted conversations and a runner. |
| `approval_flow.py` | Hold, approve, finish once. `--auto-approve` approves via the API. |
| `check.py` | Runs everything and asserts the outcomes. |
| `approvals.py` | Every way an approval ends: approve, deny, changed call, held message, expiry. |
| `modes.py` | The same attacks while watching, enforcing and asking a person. |
| `common.py` | Gateway address, operator header, the blocked message. |
