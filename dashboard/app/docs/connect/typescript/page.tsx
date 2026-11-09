import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, NextSteps, Step, Steps } from "@/components/docs/blocks";
import { REPO_URL, publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "TypeScript SDK",
  description:
    "Check a TypeScript agent's messages, answers and tool calls against AgentFox with @agentfox/sdk: guardInput, guardOutput, guardToolCall and wrapTool.",
  path: "/docs/connect/typescript",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>TypeScript SDK</h1>
      <p className="docs-lede">
        Ask AgentFox about each message, answer and tool call from a TypeScript or JavaScript agent.
        The SDK is a thin client for the gateway&apos;s guard API, with no runtime dependencies.
      </p>

      <h2>Before you start</h2>
      <ul>
        <li>Node 18 or newer, Deno, Bun, a browser or an edge runtime: it uses the global <code>fetch</code>.</li>
        <li>
          Your gateway&apos;s URL and a key: the server and key from your setup card, or a local
          gateway (<code>agentfox serve</code>, on <code>http://127.0.0.1:8080</code>).
        </li>
        <li>
          There is no <code>auto()</code> for TypeScript: you call the SDK where your agent reads
          input, answers and runs tools.
        </li>
      </ul>

      <Steps>
        <Step title="Install it">
          <Code>{`npm install @agentfox/sdk`}</Code>
          <p>
            The source is <a href={`${REPO_URL}/tree/main/sdk/typescript`}>sdk/typescript</a> in the
            repository. If npm still serves an older version than the repository, install from there.
          </p>
        </Step>

        <Step title="Check what goes in and what comes out">
          <Code lang="ts" title="agent.ts">{`import { AgentFox } from "@agentfox/sdk";

const fox = new AgentFox({
  baseUrl: process.env.AGENTFOX_URL!,
  apiKey: process.env.AGENTFOX_API_KEY,
  agent: "support-triage", // your agent's name
});

const input = await fox.guardInput(userText, { sessionId });
if (input.stopped) return input.userMessage ?? "Sorry, I can't help with that.";

const answer = await callYourModel(userText);

const output = await fox.guardOutput(answer, { traceId: input.traceId ?? undefined });
if (output.stopped) return output.userMessage ?? "Sorry, I can't help with that.";
return output.content ?? answer; // the redacted text when the verdict redacts`}</Code>
          <p>
            Each call returns a result with <code>verdict</code> (what happened; gate on it),{" "}
            <code>effectiveVerdict</code> (what the policy says, which differs while a rule is in
            Watch), <code>stopped</code>, <code>userMessage</code>, <code>approvalId</code> and{" "}
            <code>rulesFired</code>.
          </p>
        </Step>

        <Step title="Check each tool call before it runs">
          <Code lang="ts">{`const refund = fox.wrapTool(
  async (args: { order_id: string; amount: number }) => payments.refund(args),
  { tool: "payments.refund", provenance: { order_id: "user" } },
);
await refund({ order_id: "o_123", amount: 40 });`}</Code>
          <p>
            <code>provenance</code> says where each argument came from, so a value copied out of a web
            page is treated differently from one the user typed. A refused call throws{" "}
            <code>PolicyViolation</code>; a call held for a person throws <code>ApprovalRequired</code>{" "}
            with an <code>approvalId</code>. <code>fox.waitForApproval(id)</code> waits for the
            decision; retry with <code>guardToolCall(tool, args, provenance, {"{ approvalId }"})</code>{" "}
            and an approved call goes through once. Pass <code>onBlock</code> to return a value instead
            of throwing. <code>fox.guardToolCall()</code> is the same check without the wrapper.
          </p>
          <p>
            Until the agent is granted the tool (its <strong>Access</strong> tab, or{" "}
            <code>agentfox permit grant &lt;agent&gt; payments.refund --yes</code>), the call is
            refused by default-deny.
          </p>
        </Step>
      </Steps>

      <Callout kind="note" title="Or change only the base URL">
        An OpenAI client pointed at the gateway&apos;s <code>/v1</code> is checked with no SDK at all.
        See <Link href="/docs/connect/http">Any language (HTTP)</Link>.
      </Callout>

      <NextSteps
        items={[
          { href: "/docs/govern", label: "Tool access", why: "grant the tools your agent calls" },
          { href: "/docs/govern/approvals", label: "Approvals", why: "decide the calls held for a person" },
          { href: "/docs/reference/api", label: "HTTP API reference", why: "every field the SDK sends" },
        ]}
      />
    </article>
  );
}
