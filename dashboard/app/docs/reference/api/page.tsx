import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code } from "@/components/docs/blocks";
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
        <code>scripts/docs_reference.py</code>. A running gateway serves the same document
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
  -H "X-Nometria-Agent: support-triage" \\
  -d '{"agent": "support-triage", "tool": "tickets.close",
       "arguments": {"ticket_id": "T-1042"},
       "provenance": {"ticket_id": "user"},
       "intent": "close tickets the customer asked to close"}'`}</Code>
      <p>
        Worked examples for each endpoint are in the guides:{" "}
        <Link href="/docs/guides/gateway">Any language: the gateway</Link> covers the
        proxies and guard calls; <Link href="/docs/guides/approvals">Approvals</Link> covers
        polling an escalation.
      </p>

      <Callout kind="note">
        <p>
          Header names still carry the old product name (<code>X-Nometria-Agent</code>,{" "}
          <code>X-Nometria-Verdict</code>). They are the wire protocol, and renaming them
          would break existing clients.
        </p>
      </Callout>

      <h2 id="agent-traffic">Agent traffic</h2>
      <ApiReference audience="public" />

      <h2 id="operator">Operator API</h2>
      <ApiReference audience="operator" />

      <h2 id="unauthenticated">Public, unauthenticated</h2>
      <p>The playground and the waitlist. Sandboxed, rate-limited, and separate from your data.</p>
      <ApiReference audience="public-unauthenticated" />
    </article>
  );
}
