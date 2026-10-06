---
name: integrate-guardrails
description: Wires AgentFox into specific application code beyond the one-liner. It declares tools with impact levels, marks retrieved and tool-returned content as untrusted so taint containment works, and integrates LangGraph nodes, FastAPI endpoints, MCP clients or the gateway proxy, with a test that proves a tainted irreversible call escalates. Use when an agent has side-effecting tools, uses LangGraph/FastAPI/MCP, uses async or streaming clients, or `agentfox scan` shows calls auto() can't govern.
---

# Integrate guardrails

> Commands below are written as `agentfox …`. If `agentfox` isn't on PATH, see
> [Running the CLI](../../AGENTS.md#running-the-cli).

The one-liner governs model *text*. The product's strongest guarantee is about *actions*.
An irreversible tool can't take arguments that came from untrusted content without a human.
That guarantee only holds when the code tells AgentFox two things:

1. **What each tool can do.** This is its `impact`: `read`, `write`, `high_impact` or
   `irreversible`.
2. **Where content came from.** Retrieved documents, tool results and sub-agent output are
   untrusted.

Every step below serves one of those two facts. Signatures are in
[reference/sdk.md](../../reference/sdk.md).

## 1. Inventory

List every function the agent can call that has a side effect: payments, refunds, emails,
tickets, SQL writes, file writes, deploys. For each one, record:

| Tool key (stable, dotted) | What it does | Impact | Arguments that matter |
|---|---|---|---|
| `payments.refund` | refunds a charge | irreversible | amount, charge_id |

Confirm the impact classification with the user. When in doubt, go one level up: an
irreversible action that is mis-declared as `write` loses the human-in-the-loop guarantee.

## 2. Pick the surface for this code

| The code is… | Do this |
|---|---|
| plain Python with tool functions | `AgentFox` SDK: `@nom.tool(key, impact=...)` plus `with nom.session(intent=...)`; wrap fetched content with `s.retrieved(...)` / `s.tool_result(...)` |
| a LangGraph graph | `AgentFoxGuard`: `retrieval_node` for fetchers, `model_node` for LLM calls, `tool_node(fn, tool=key)` for tools |
| a FastAPI service | `install(app)` for observe middleware; `Depends(guard(agent=..., field="prompt"))` on prompt-taking endpoints |
| an MCP client | `McpGovernor`: `register_tools` once, then `gov.call(...)` instead of calling the server directly |
| streaming that must be cut mid-response, or not Python | gateway proxy: set `base_url` to `http://<gateway>:8080/v1` and send `X-Nometria-Agent` plus `X-Nometria-Trust` for untrusted message indices |

Several can coexist. For example, `auto()` for model calls plus the SDK for tools.

## 3. Declare intent

Pass a short `intent` for the session, such as "refund a duplicate charge". The
`intent.undeclared_irreversible` rule in `tool-containment` escalates irreversible calls
made with no declared intent.

## 4. Handle the outcomes in code

- `ApprovalRequired`: the action is waiting for a human. Surface `approval_id` to the user,
  and don't retry in a loop.
- `PolicyViolation` or `agentfox.Blocked`: tell the user it was refused, and log `rules_fired`.
- **Redaction:** the returned content is already redacted. Use it, not the original.

While the relevant policies observe, none of these are raised. The code must be ready for
when someone runs `policy enforce`, because `auto()` and the SDK follow it with no code change.

## 5. Prove it with a test

Add a test that runs against a scratch DB. It feeds a "retrieved" document that carries an
account number, passes that value to the irreversible tool, and asserts that
`ApprovalRequired` is raised. Build it from the SDK example in [reference/sdk.md](../../reference/sdk.md). Set
`NOMETRIA_DATABASE_URL` to a tmp path in the test. The test may run enforce mode; the
application code stays in observe.

Also check the negative case: the same call with a user-supplied value is allowed.

## 6. Verify end to end

```bash
agentfox scan . --json       # the call sites now show as governed
agentfox agents lineage <slug> # tools appear with their impact
agentfox findings --json
```

Report three things: the files changed, the new test and how to run it, and any calls
still ungoverned, with the reason.
