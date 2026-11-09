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
  -H "Authorization: Bearer $AGENTFOX_API_KEY" \\
  -H "X-AgentFox-Agent: support-triage" \\
  -d '{"agent": "support-triage", "tool": "tickets.close",
       "arguments": {"ticket_id": "T-1042"},
       "provenance": {"ticket_id": "user"},
       "intent": "close tickets the customer asked to close"}'`}</Code>
      <Output title="On a fresh install (trimmed)">{`HTTP/1.1 200 OK
{"verdict":"allow", "effective_verdict":"block", "mode":"observe",
 "rules_fired":[{"rule_id":"capability.default_deny", "effect":"block", "mode":"observe", ...}],
 "reason":"'tickets.close' has not been granted to this agent yet (default deny). Allow it in
   the dashboard (the agent's Access tab), or run \`agentfox permit grant <agent> tickets.close\`.",
 "explanation":{..., "dispute":{"endpoint":"POST /api/guardrails/feedback", ...}}}`}</Output>
      <p>
        A verdict is a 200 with a body, not an error status: your code reads{" "}
        <code>verdict</code> and decides. On a fresh install every library watches, so{" "}
        <code>verdict</code> is <code>allow</code> and <code>effective_verdict</code> says
        what it would have done: nothing is granted yet, so default-deny would refuse it, and
        the reason says how to fix it. Once <code>agentfox policy enforce tool-containment</code>{" "}
        has run, the same call returns <code>&quot;verdict&quot;:&quot;block&quot;</code>.
      </p>
      <p>
        Worked examples for each endpoint are in the guides:{" "}
        <Link href="/docs/connect/http">Any language: the gateway</Link> covers the
        proxies and guard calls; <Link href="/docs/govern/approvals">Approvals</Link> covers
        polling an escalation.
      </p>

      <h2 id="notes">Notes on the main routes</h2>
      <p>
        Proxy request and response headers, status codes (403 blocked, 428 held, 429 shed,
        503 degraded) and streaming modes are in{" "}
        <Link href="/docs/reference/config#gateway">Configuration: gateway requests</Link>.
      </p>

      <h3 id="guard-tool-call">/v1/guard/tool_call</h3>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr><th>Field</th><th>What it does</th></tr>
        </thead>
        <tbody>
          <tr><td><code>agent</code>, <code>tool</code>, <code>arguments</code></td><td>Required. For an MCP tool the key is <code>mcp:&lt;server&gt;/&lt;tool&gt;</code>.</td></tr>
          <tr><td><code>provenance</code></td><td>Argument name to source (<code>user</code>, <code>retrieved</code>, <code>tool_result</code>, …). Declared provenance is believed.</td></tr>
          <tr><td><code>intent</code>, <code>session_id</code></td><td>The declared task; the conversation.</td></tr>
          <tr><td><code>messages</code></td><td>The conversation that led to the call (OpenAI or Anthropic shape). An undeclared argument is traced to where it appears in it. With neither this nor <code>provenance</code>, arguments are treated as untainted.</td></tr>
          <tr><td><code>trust</code></td><td>Message index to source, for messages you vouch for.</td></tr>
          <tr><td><code>prior_tools</code>, <code>prior_steps</code></td><td>Your own step history, for loop detection.</td></tr>
          <tr><td><code>in_process</code></td><td>What you will do with the verdict: <code>enforced</code> (default), <code>all</code> or <code>none</code>. Findings then say whether the call was really stopped.</td></tr>
          <tr><td><code>waive_ungranted</code></td><td>While the agent holds no grant at all, a missing grant is recorded, not applied; listed in <code>waived_rules</code>.</td></tr>
          <tr><td><code>declare</code></td><td>The tool&apos;s declaration as the model saw it; a new tool is registered with an inferred impact.</td></tr>
        </tbody>
      </table></div>
      <p>
        Every decision is a 200 with a <code>verdict</code>. An <code>escalate</code> carries{" "}
        <code>approval_id</code> and a <code>reason</code>: do not run the tool yet.
      </p>

      <h3 id="approvals">Redeeming an approval</h3>
      <p>
        Poll <code>GET /api/approvals/&#123;id&#125;</code> (an agent key may read its own
        agent&apos;s). Once it is <code>approved</code>, repeat the same call: on the proxy with{" "}
        <code>X-AgentFox-Approval: apr_…</code> after its 428, on the guard routes with{" "}
        <code>approval_id</code> in the body. It runs once.
      </p>

      <h3 id="mcp-call">/v1/mcp/call</h3>
      <p>
        Send <code>server</code>, <code>tool</code>, <code>arguments</code>, optional{" "}
        <code>provenance</code>, and the <code>result</code> you got: the gateway never dials
        the server. It answers with <code>result</code> (possibly redacted),{" "}
        <code>key</code> (<code>mcp:&lt;server&gt;/&lt;tool&gt;</code>), <code>allowed</code>{" "}
        and the <code>pre</code> and <code>post</code> decisions, or 403 when it refuses. The
        side effect has already happened by then, so authorise a tool that changes something
        first with <code>/v1/guard/tool_call</code>.
      </p>
      <p>
        <code>POST /api/mcp-servers/&#123;name&#125;/tools</code> registers a listing. A changed
        tool is held (calls refused as <code>mcp.schema_drift</code>) and filed as a proposal;{" "}
        <code>&quot;accept_changes&quot;: true</code> is the signed-in person&apos;s approval, and the
        tool stays <code>awaiting_second_approver</code> until a different person approves
        (here or <code>POST /api/proposals/&#123;id&#125;/decide</code>).
      </p>

      <h3 id="credentials">Agent credentials</h3>
      <p>
        <code>POST /api/identities/&#123;id&#125;/credentials?ttl_days=90</code> (security, admin
        or owner) returns an agent key (<code>nom_agt_…</code>) once. Find the identity whose
        principal is <code>agent:&lt;slug&gt;</code> with <code>GET /api/identities</code>. On{" "}
        <code>/v1</code> an unknown key is treated as no credential, not refused.
      </p>

      <h3 id="entitlement-filter">/api/entitlement/filter</h3>
      <p>
        Takes <code>subject</code>, <code>chunks</code> (each <code>source</code>,{" "}
        <code>text</code>) and optional <code>purpose</code>, <code>agent</code>,{" "}
        <code>trace_id</code>. Returns <code>chunks</code> (what this person may see),{" "}
        <code>principal</code>, <code>candidates</code>, <code>visible</code>,{" "}
        <code>withheld</code>, <code>reasons</code> (counts such as <code>not_entitled</code>),{" "}
        <code>over_permission</code> and <code>withheld_sources</code>. Call it between
        retrieval and generation.
      </p>

      <h3 id="suppressions">/api/guardrails/suppressions</h3>
      <p>
        Fields and rules are in <Link href="/docs/reference/detectors#suppressions">Detectors: suppressions</Link>{" "}
        (<code>scope</code> agent or global, <code>exact</code>, <code>ttl_days</code> 1 to 365).
      </p>

      <h3 id="proxy-limits">Limits</h3>
      <ul>
        <li>The proxy has no route for the OpenAI Responses API.</li>
        <li>A streamed Anthropic reply carries text only; do not stream tool use through <code>/v1/messages</code>.</li>
        <li>Provenance and trust you declare are believed: a caller that labels a tool result as <code>user</code> gets a <code>user</code> decision.</li>
      </ul>

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
