# @agentfox/sdk

TypeScript client for the AgentFox guard endpoints. No runtime dependencies; uses the global
`fetch` (Node 18+, Deno, Bun, browsers, edge runtimes).

```bash
npm install @agentfox/sdk
```

## Guard inputs, outputs and tool calls

```ts
import { AgentFox, ApprovalRequired, PolicyViolation } from "@agentfox/sdk";

const fox = new AgentFox({
  baseUrl: "http://localhost:8080",
  agent: "support-triage",
  apiKey: process.env.AGENTFOX_AGENT_KEY, // optional; binds the agent's tenant
});

const input = await fox.guardInput(userText, { sessionId });
if (input.stopped) return input.userMessage ?? "Sorry, I can't help with that.";

const answer = await callYourModel(userText);

const output = await fox.guardOutput(answer, { traceId: input.traceId ?? undefined, context: passages });
if (output.fix) {
  // a re-ask rule fired: send output.fix.instruction to the model and try again
}
if (output.stopped) return output.userMessage ?? "Sorry, I can't help with that.";
return output.content ?? answer; // content is the redacted text when the verdict redacts
```

```ts
const decision = await fox.guardToolCall(
  "payments.refund",
  { order_id: "o_123", amount: 40 },
  { order_id: "user" }, // provenance: where each argument came from
);
```

Each call returns a `GuardResult`:

| Field | Meaning |
|---|---|
| `verdict` | What happened to the request (the applied verdict). Gate on this. |
| `effectiveVerdict` | What the policy says should happen. In observe mode, the one that did not take effect. |
| `stopped`, `blocked`, `escalated` | `verdict` is block, escalate or abstain; block; escalate. |
| `userMessage` | The deciding rule's message, safe to show the end user. |
| `fix` | `{ instruction }` when a re-ask rule fired on an output. |
| `approvalId` | Set on `escalate`: the approval to wait on and retry with. |
| `traceId`, `decisionId`, `rulesFired`, `entities`, `reason`, `content`, `explainUrl` | The rest of the decision. `raw` is the body as sent. |

## Wrap a tool

```ts
const refund = fox.wrapTool(
  async (args: { order_id: string; amount: number }) => payments.refund(args),
  { tool: "payments.refund", provenance: { order_id: "user" } },
);

const args = { order_id: "o_123", amount: 40 };
try {
  await refund(args);
} catch (err) {
  if (err instanceof ApprovalRequired) {
    if ((await fox.waitForApproval(err.approvalId!)) === "approved") {
      const retry = await fox.guardToolCall("payments.refund", args, {}, { approvalId: err.approvalId! });
      if (!retry.stopped) await payments.refund(args); // the approval lets this call through once
    }
  } else if (err instanceof PolicyViolation) {
    console.warn("blocked", err.result.rulesFired);
  } else throw err;
}
```

Pass `onBlock: (result) => value` to return a value (for example a refusal message for the
model) instead of throwing.

## OpenAI-compatible proxy

The gateway also proxies `/v1/chat/completions`, so an existing OpenAI client needs only a new
base URL and the agent header:

```ts
import OpenAI from "openai";

const openai = new OpenAI({
  baseURL: "http://localhost:8080/v1",
  apiKey: process.env.AGENTFOX_AGENT_KEY,
  defaultHeaders: { "X-AgentFox-Agent": "support-triage" },
});
```

A blocked call raises `APIError` with status 403; a call held for a person raises with status 428
and `error.approval_id`. Once approved, resend it with the header `X-AgentFox-Approval: <id>`.

## Develop

```bash
npm install
npm run typecheck
npm test
npm run build
```
