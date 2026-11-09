import type { Metadata } from "next";
import Link from "next/link";

import { Code, NextSteps, Step, Steps } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Any language (HTTP)",
  description:
    "Send an agent's model calls through the AgentFox proxy, or ask the guard API before a tool runs, from any language.",
  path: "/docs/connect/http",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>Any language (HTTP)</h1>
      <p className="docs-lede">
        Get the same checks as <code>agentfox.auto()</code> from TypeScript, Go, Java or anything that
        speaks HTTP: change your client&apos;s base URL, or ask AgentFox before a tool runs.
      </p>

      <h2>Before you start</h2>
      <ul>
        <li>
          The server URL from your setup card, or a local gateway: <code>agentfox serve</code> listens on{" "}
          <code>http://127.0.0.1:8080</code>.
        </li>
      </ul>

      <Steps>
        <Step title="Point your client at the proxy">
          <p>
            Any OpenAI-compatible client works. Set the base URL to the gateway&apos;s <code>/v1</code> and
            name the agent in a header. Anthropic clients use <code>/v1/messages</code> the same way.
          </p>
          <Code lang="ts" title="agent.ts">{`const client = new OpenAI({
  baseURL: "http://localhost:8080/v1",
  defaultHeaders: { "X-AgentFox-Agent": "support-triage" },
});`}</Code>
          <p>
            The prompt, the answer and every tool call the model asks for are checked before the
            response reaches you. Streaming works.
          </p>
        </Step>

        <Step title="Handle a refusal">
          <p>
            A blocked request is a <strong>403</strong>. Do not retry it; log the <code>trace_id</code>. A
            call held for a person is a <strong>428</strong> with an <code>approval_id</code>. Once it is
            approved, send the same request with <code>X-AgentFox-Approval: apr_…</code> and it runs once.
          </p>
        </Step>

        <Step title="Or check a tool call before it runs">
          <p>
            If you call the model yourself, ask AgentFox before each tool runs. Say where each argument
            came from, so an id copied out of a web page is treated differently from one the user typed.
          </p>
          <Code>{`curl -s http://localhost:8080/v1/guard/tool_call -H 'Content-Type: application/json' \\
  -d '{"agent": "support-triage", "tool": "tickets.close",
       "arguments": {"ticket_id": "T-4411"}, "provenance": {"ticket_id": "user"}}'`}</Code>
          <p>
            This route always answers <strong>200</strong>, even for a refusal. Read{" "}
            <code>verdict</code>: run the tool only on <code>allow</code>. On <code>escalate</code>, wait
            for the <code>approval_id</code> to be decided. On <code>block</code>, do not run it.
          </p>
        </Step>

        <Step title="See it in the app">
          <p>
            Each request appears on the agent&apos;s <strong>Activity</strong> tab and on{" "}
            <strong>Traces</strong>, with the rule that decided it.
          </p>
        </Step>
      </Steps>

      <h2>Headers worth sending</h2>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr>
            <th>Header</th>
            <th>What it does</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><code>X-AgentFox-Agent</code></td>
            <td>The agent&apos;s name. Without it, no grant or agent rule applies.</td>
          </tr>
          <tr>
            <td><code>X-AgentFox-Session</code></td>
            <td>Ties calls into one conversation, so runaway tool loops are caught.</td>
          </tr>
          <tr>
            <td><code>X-AgentFox-Intent</code></td>
            <td>The task the agent is on. Tool calls are checked against it.</td>
          </tr>
        </tbody>
      </table></div>
      <p>
        Every route and field is in the <Link href="/docs/reference/api">HTTP API reference</Link>. Headers,
        streaming modes and status codes are under{" "}
        <Link href="/docs/reference/config#gateway">Gateway requests</Link>. Text checks (
        <code>/v1/guard/input</code>, <code>/v1/guard/output</code>), memory writes and MCP results have
        their own guard routes there too.
      </p>
      <p>
        <code>/v1</code> does not check an operator login. Keep the gateway on a private network, and give
        each agent a key (<code>Authorization: Bearer nom_agt_…</code>) so calls are tied to it.
      </p>

      <h2>If something goes wrong</h2>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr>
            <th>You see</th>
            <th>Do this</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Everything is allowed, and <code>x-agentfox-would-be-verdict</code> says <code>block</code></td>
            <td>The guardrail is in Watch. <Link href="/docs/protect">Switch it to Block</Link> when you are ready.</td>
          </tr>
          <tr>
            <td>A grant has no effect</td>
            <td>The <code>X-AgentFox-Agent</code> header (or <code>agent</code> field) must match the agent&apos;s name exactly.</td>
          </tr>
          <tr>
            <td>A self-hosted gateway cannot reach your model provider</td>
            <td>
              Set <code>AGENTFOX_ALLOW_EGRESS=true</code> and the provider&apos;s key (
              <Link href="/docs/reference/config">Configuration</Link>).
            </td>
          </tr>
        </tbody>
      </table></div>

      <NextSteps
        items={[
          { href: "/docs/govern", label: "Tool access", why: "the grants /v1/guard/tool_call reads" },
          { href: "/docs/govern/approvals", label: "Approvals", why: "what to do with a 428 or an escalate" },
          { href: "/docs/self-host", label: "Self-host", why: "run the gateway yourself" },
        ]}
      />
    </article>
  );
}
