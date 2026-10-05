import type { Metadata } from "next";
import Link from "next/link";

import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Where AgentFox connects",
  description: "Python, the HTTP gateway, LangGraph, and the headers a proxied model call returns.",
  path: "/docs/connect",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Start</p>
      <h1>Where it connects</h1>
      <p>
        One policy, several places it can bind. Connecting one does not cover the
        others. A claim that flattened them would hide what each surface actually sees.
      </p>

      <h2>Python</h2>
      <pre>
        <code>{`import agentfox
agentfox.auto()`}</code>
      </pre>
      <p>
        One line in the entry point. Every model call in the process is traced,
        evaluated, and written to the audit log: OpenAI chat completions, Anthropic
        messages, LiteLLM, and LangChain, sync, async, and streamed. Nothing else in
        the application changes. The tool calls in each response (OpenAI{" "}
        <code>tool_calls</code>, Anthropic <code>tool_use</code>) are checked before
        your code can run them, with argument provenance read from the conversation,
        and a tool seen for the first time is registered with an inferred impact for
        you to confirm.
      </p>
      <p>
        Nothing is blocked by the line itself. <code>auto()</code> follows each
        policy&apos;s own mode, <code>baseline</code> starts in observe, and capability
        default-deny applies once the agent holds its first grant. When a tool call is
        refused, <code>agentfox.Blocked</code> is raised in place of the response. It
        does not see the OpenAI Responses API, or tools your code calls without the
        model asking.
      </p>

      <h2>Any language, over HTTP</h2>
      <pre>
        <code>{`agentfox serve
agentfox admin auth issue you@example.com`}</code>
      </pre>
      <p>
        <code>serve</code> is the gateway and the control-plane API on{" "}
        <code>127.0.0.1:8080</code>. Point an existing OpenAI or Anthropic client at{" "}
        <code>http://localhost:8080/v1</code> and change nothing else, or ask about one
        tool call:
      </p>
      <pre>
        <code>{`curl -s -X POST http://localhost:8080/v1/guard/tool_call \\
  -H "Authorization: Bearer $AGENTFOX_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"agent":"payments-ops","tool":"payments.transfer",
       "arguments":{"amount":250,"currency":"USD","to":"acct_991"},
       "provenance":{"to":"tool_result","amount":"user"},
       "intent":"refund a duplicate charge"}'`}</code>
      </pre>
      <p>
        With the recipient marked <code>tool_result</code>, the verdict is{" "}
        <code>escalate</code> and the response carries an <code>approval_id</code>.
        Mark <code>to</code> as <code>user</code> and the same call returns{" "}
        <code>allow</code>. The <code>/v1/guard/*</code> routes used during the first
        hour do not require a token. The control-plane API under <code>/api</code>{" "}
        does. <code>auth issue</code> mints a token for an operator that already
        exists, shown once and hashed at rest. A database from <code>agentfox init</code>{" "}
        alone has no operators. The first account comes from <code>agentfox admin seed</code>{" "}
        (which creates <code>admin@example.com</code>) or from signing in to the
        dashboard with GitHub. <code>agentfox admin auth status</code> says whether this
        deployment is actually requiring tokens. In development it accepts an{" "}
        <code>X-Nometria-User</code> header instead, which is fine locally and
        unacceptable anywhere else.
      </p>
      <p>
        Sibling guard routes are <code>/v1/guard/input</code>, <code>/v1/guard/output</code>,{" "}
        <code>/v1/guard/memory_write</code>, <code>/v1/guard/agent_message</code>, and{" "}
        <code>/v1/mcp/call</code>. The full surface is Appendix C in the repository.
      </p>

      <h3>Headers on a proxied model call</h3>
      <p>The response carries the decision:</p>
      <pre>
        <code>{`x-nometria-trace: trc_01m376q450vgp786rg
x-nometria-verdict: allow
x-nometria-effective-verdict: allow
x-nometria-mode: enforce
x-nometria-latency-ms: 2.72`}</code>
      </pre>
      <p>
        <code>x-nometria-verdict</code> is what happened.{" "}
        <code>x-nometria-effective-verdict</code> is what the policy would have done
        regardless of mode. In observe they differ, and that gap is what you watch
        before <Link href="/docs/runtime">turning enforcement on</Link>.
      </p>
      <p>
        Useful request headers: <code>X-Nometria-Agent</code> (the agent slug),{" "}
        <code>X-Nometria-Session</code> (calls in one execution path),{" "}
        <code>X-Nometria-Intent</code> (the declared task), and{" "}
        <code>X-Nometria-Trust</code> (a JSON map marking message indices as untrusted,
        for example <code>{`{"2":"retrieved"}`}</code>).
      </p>

      <h2>LangGraph</h2>
      <pre>
        <code>{`from agentfox.integrations.langgraph import AgentFoxGuard

guard = AgentFoxGuard(agent="support-triage", intent="answer a refund question")

builder.add_node("retrieve", guard.retrieval_node(fetch_docs))
builder.add_node("model", guard.model_node(call_model))
builder.add_node("pay", guard.tool_node(transfer, tool="payments.transfer"))`}</code>
      </pre>
      <p>
        Trace identity lives in graph state, so it survives checkpointing and
        resumption. An escalation maps to LangGraph&apos;s own <code>interrupt()</code>.
        Needs the <code>langgraph</code> extra.
      </p>

      <h2>Retrieval</h2>
      <p>
        Call <code>filter_retrieval()</code> from your own retrieval code, or use the
        HTTP endpoint. What the person asking is not allowed to see does not come back,
        and does not reach the prompt. This is not on unless you call it. The answer
        boundary is also off until you declare what the agent knows.
      </p>
      <p>
        Coding-agent hooks and MCP are separate surfaces:{" "}
        <Link href="/docs/hooks">Coding agents</Link> and <Link href="/docs/mcp">MCP</Link>.
      </p>
    </article>
  );
}
