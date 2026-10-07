import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, Output } from "@/components/docs/blocks";
import { API_COUNT, ApiReference } from "@/components/docs/reference";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "HTTP API reference",
  description: "Every gateway route, generated from the gateway's OpenAPI document.",
  path: "/docs/reference/api",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Reference</p>
      <h1>HTTP API reference</h1>
      <p className="docs-lede">
        All {API_COUNT} routes the gateway serves, generated from its OpenAPI document by{" "}
        <code>scripts/gen/docs_reference.py</code>. A running gateway serves the same document
        at <code>/openapi.json</code> and an explorer at <code>/docs</code>.
      </p>

      <h2>Two audiences</h2>
      <p>
        <strong>Agent traffic</strong> (<code>/v1/*</code>) is what your application calls
        on every request: the OpenAI- and Anthropic-compatible proxies, and the guard
        endpoints that check content and tool calls without proxying. It authenticates
        as an agent. <strong>The operator API</strong> (<code>/api/*</code>) is what the
        web app, the CLI and your scripts use to manage agents, policies, findings and
        evidence. It takes a bearer token from <code>agentfox admin auth issue</code>.
      </p>
      <Code title="Check a tool call before running it">{`curl -s http://localhost:8080/v1/guard/tool_call \\
  -H "Content-Type: application/json" \\
  -H "X-AgentFox-Agent: support-triage" \\
  -d '{"agent": "support-triage", "tool": "tickets.close",
       "arguments": {"ticket_id": "T-1042"},
       "provenance": {"ticket_id": "user"},
       "intent": "close tickets the customer asked to close"}'`}</Code>
      <Output title="On a fresh install (trimmed)">{`HTTP/1.1 200 OK
{"verdict":"block", "mode":"enforce",
 "rules_fired":[{"rule_id":"capability.denied", ...},
                {"rule_id":"tool.not_declared", "effect":"escalate", ...}],
 "reason":"no resolved identity for the caller, so it holds no grants (default deny).
   To have grants proposed from the calls this agent has made, run
   \`agentfox policy proposals from-traffic\` and approve them; ...",
 "explanation":{..., "dispute":{"endpoint":"POST /api/guardrails/feedback", ...}}}`}</Output>
      <p>
        A verdict is a 200 with a body, not an error status: your code reads{" "}
        <code>verdict</code> and decides. Nothing is granted on a fresh install, so the
        first call is refused by default-deny, and the reason says how to fix it.
      </p>
      <p>
        Worked examples for each endpoint are in the guides:{" "}
        <Link href="/docs/guides/gateway">Any language: the gateway</Link> covers the
        proxies and guard calls; <Link href="/docs/guides/approvals">Approvals</Link> covers
        polling an escalation.
      </p>

      <Callout kind="note">
        <p>
          Headers are <code>X-AgentFox-*</code>.
        </p>
      </Callout>

      <h2 id="agent-traffic">Agent traffic</h2>
      <ApiReference audience="public" />

      <h2 id="operator">Operator API</h2>
      <ApiReference audience="operator" />

      <h2 id="unauthenticated">Public, unauthenticated</h2>
      <p>The playground, the waitlist and the live showcase feed. Sandboxed or read-only, rate-limited, and separate from your data.</p>
      <ApiReference audience="public-unauthenticated" />
    </article>
  );
}
