<div align="center">

<img src="docs/assets/mark.webp" width="72" alt="" />

# AgentFox

**Know when your AI agent should stop.**

An open-source control plane that checks what your agent may read, may claim and may do —
and refuses the rest. It holds after the model has already been convinced.

[![CI](https://github.com/architsharm/agentfox/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/architsharm/agentfox/actions/workflows/ci.yml) [![Licence](https://img.shields.io/badge/licence-Apache--2.0-2f6feb.svg)](LICENSE) [![Python](https://img.shields.io/badge/python-3.11%2B-2f6feb.svg)](pyproject.toml) [![PyPI](https://img.shields.io/pypi/v/agentfox.svg?color=2f6feb)](https://pypi.org/project/agentfox/) [![Status](https://img.shields.io/badge/status-early%20release-8a5a00.svg)](docs/status.md) [![Playground](https://img.shields.io/badge/playground-no%20account-c23600.svg)](https://useagentfox.com/playground)

**[▶ Try it live, no account](https://useagentfox.com/playground)** &nbsp;·&nbsp; [🚀 Self-host it](docs/product-tour.md#self-hosting) &nbsp;·&nbsp; [📊 Every benchmark](https://useagentfox.com/benchmark) &nbsp;·&nbsp; [⚖ How we compare](https://useagentfox.com/compare)

[Docs](https://useagentfox.com/docs) · [Getting started](docs/getting-started.md) · [Architecture](ARCHITECTURE.md) · [Contributing](CONTRIBUTING.md) · [What is built](docs/status.md) · [Discussions](https://github.com/architsharm/agentfox/discussions)

</div>

<br />

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/hero-dark.webp" />
  <img src="docs/assets/hero-light.webp" alt="Four tool calls from one agent. Three are allowed; payments.transfer is refused by capability.denied, with the reason shown." />
</picture>

## What it does

AgentFox sits on your agent's model and tool calls, in-process or as an HTTP gateway, and
decides whether each one may happen. Every tool carries a declared impact tier, every agent
holds explicit capability grants with argument limits, and every argument carries the
provenance of where its value came from. A transfer whose recipient came out of a retrieved
document is refused because of *where the value came from*, not because a detector
recognised the payload. Every decision lands in a tamper-evident audit chain that an auditor
can verify without trusting us.

| | Question | On by default |
|---|---|---|
| **Read** | Is this person allowed to see this retrieved content? | You call it from your retrieval code |
| **Answer** | Is this inside what the agent knows? | After you declare a knowledge boundary |
| **Act** | Was this agent granted this call, with these values, from these sources? | **Yes**: `tool-containment` ships enforcing |

## Quickstart

```bash
pip install agentfox
agentfox init && agentfox demo
```

`init` creates a SQLite database and loads 43 controls and the policy packs, in about a
second. `demo` runs a thirteen-step walkthrough in about five. Both are offline: no API key, no
downloaded weights, no network egress. Or scan the directory you are in without installing:

```bash
curl -fsSL https://raw.githubusercontent.com/architsharm/agentfox/main/scripts/quickscan.sh | bash
```

Then govern your own agent with one line:

```python
import agentfox
agentfox.auto()
```

Every OpenAI, Anthropic, LiteLLM and LangChain call in the process is traced, evaluated and
audited, and every tool call in a response is checked before your code can run it. Nothing is
blocked by the line itself: content policies start in observe, and tool containment enforces
after `agentfox init`, raising `agentfox.Blocked` for a refused call.

## Contain a tool call

Any language can ask the gateway about one call before running it:

```bash
agentfox serve                              # gateway + control-plane API on 127.0.0.1:8080
agentfox admin users create you@example.com --token   # first operator + API token, shown once

curl -s -X POST http://localhost:8080/v1/guard/tool_call \
  -H "Authorization: Bearer $AGENTFOX_TOKEN" -H "Content-Type: application/json" \
  -d '{"agent":"payments-ops","tool":"payments.transfer",
       "arguments":{"amount":250,"currency":"USD","to":"acct_991"},
       "provenance":{"to":"tool_result","amount":"user"},
       "intent":"refund a duplicate charge"}' | jq '{verdict, approval_id}'
```

```json
{ "verdict": "escalate", "approval_id": "apr_01m376q43zby33tbsp" }
```

The recipient came from a tool result, so the transfer waits for a human. Flip `"to"` to
`"user"` and the same call returns `allow`. Once a person approves it
(`agentfox permit approvals approve apr_…`), the same call with `"approval_id"` added runs, once.
Pointed at `/v1` as an OpenAI or Anthropic base URL, the gateway proxies model calls too, and a held
one returns HTTP 428 with its `approval_id`.
LangGraph, MCP, Claude Code hooks, the SDK and the
full command set are in the [website guides](https://useagentfox.com/docs) and the
[product tour](docs/product-tour.md).

## Tracking without anyone running a command

A scan is a snapshot. Connect a GitHub repository, a hosted API's OpenAPI document or an MCP server
once and AgentFox keeps re-checking it: every few hours, and on every push once the GitHub webhook
is registered. What changed since the last run becomes a finding, and the finding closes itself
when the condition clears. Setup and every finding type:
[Monitor connected sources](https://useagentfox.com/docs/guides/monitoring).

## What we measured

We do not claim adversarial robustness, and we do not believe anyone can.
[*The Attacker Moves Second*](https://arxiv.org/abs/2510.09023) (Nasr, Carlini, Schulhoff et al.,
2025) reports over 90% attack success against twelve published defences once the attacker adapts.
So the number we lead with does not depend on catching anything: both rows below were measured
with **every detector switched off**.

| Evidence | Result |
|---|---|
| [Containment under total detector bypass](benchmarks/containment/README.md) | **8/8 attacks contained with zero detector signal**; 4/4 legitimate calls still allowed |
| [AgentDojo, replayed end to end](benchmarks/agentdojo/README.md): 97 user tasks and 949 attack pairs, with argument provenance inferred from the real tool outputs | **588/588 attack pairs contained** with session-level taint, but only **24/97 benign tasks (24.7% [17.2, 34.2]) run without escalating to a human**. Per-argument taint: 37/97 benign tasks, 527/588 attack pairs contained. Taking provenance from the benchmark's own labels gives 97/97 and 588/588; that is an upper bound, not a measurement |

The cost is benign utility: when provenance is inferred, a legitimate action that copies a
value out of a tool output looks the same as an attack, and it is escalated.

**Optionally, detection gets better.** The judgment tiers are off by default; with them on,
agentfox catches 160/165 of the injection payloads that defeated our own pattern detectors, at
94.7% precision against the [NotInject](benchmarks/generalization/data/README.md) over-defense
set. [What each tier is worth, and what it costs](benchmarks/judgment/README.md).

## Where we are still improving

Detection is the layer we trust least, so we publish its numbers.

- The default heuristic detector's held-out injection recall is **26.7%**, at 100% precision
  ([REPORT.md](benchmarks/REPORT.md)). An [adaptive attacker](benchmarks/adaptive/README.md)
  that reads our verdict and retries gets **71% of the attacks we catch through within 50
  attempts** against the default stack.
- The deterministic answerability classifier abstains on 57/676 contested questions; with a
  judgment tier that becomes 572/676, at the cost of over-refusal rising from 0.75% to 6.8%.
- Against a real, independently installed `llm-guard` on indirect injection via tool output, it
  is more precise than us: **81.8% against our 66.7%** on the same 20 cases, though of the 10
  attacks among them we catch all 10 and it catches 9
  ([agent_security](benchmarks/agent_security/README.md)).
- On AgentDojo, per-argument taint misses 61 of 702 attacker write calls; session-level taint
  misses none of them and escalates three in four benign tasks.
- The opt-in classifier ensemble reaches 85.6% and 98.6% recall on two independent datasets, but
  it is **not the shipped default**: on long prompts it mostly times out.

Treat every detection number as a speed bump that raises attacker cost, never as a defence.

## Not built yet

- **It is only as good as your declarations.** A destructive tool declared `read` is treated
  as `read`. `agentfox doctor` grades this; `agentfox scan` finds undeclared tools.
- **You declare the estate yourself.** No Okta, no DataHub; principals and grants live in AgentFox.
- **Compliance mappings are DRAFT**, not reviewed by counsel, and labelled so in every export.
- **Version 0.3.** No live IdP or SSO, single-org multi-tenancy enforced at the session, text only.

Live per-capability status, computed by probe: [docs/status.md](docs/status.md).

## Documentation

| | |
|---|---|
| [Website docs](https://useagentfox.com/docs) | Install, guides for every integration, and the CLI, API and config reference |
| [Getting started](docs/getting-started.md) | A linear first hour, ending with your own agent governed |
| [Product tour](docs/product-tour.md) | Every integration surface, commands by task, the demo output, self-hosting |
| [ARCHITECTURE.md](ARCHITECTURE.md) | The domain model, a tool call traced through the code, and the code map |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Setup in three commands, `just ci`, and the conventions |
| [docs/](docs/README.md) | Design, threat model, requirements and how the numbers were measured |
| [Benchmarks](benchmarks/README.md) | Every number above, with the script that reproduces it |
| [SECURITY.md](SECURITY.md) | Report a vulnerability privately; please not in a public issue |

Questions and ideas go to [Discussions](https://github.com/architsharm/agentfox/discussions);
bugs to [Issues](https://github.com/architsharm/agentfox/issues/new/choose). New contributors:
start with a [good first issue](https://github.com/architsharm/agentfox/labels/good%20first%20issue).

## Licence

[Apache-2.0](LICENSE). All of it, and it stays that way: no licence key, no gated features.
