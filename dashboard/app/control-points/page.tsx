/**
 * /control-points — open enforcement, in full.
 *
 * Same template as the other seven. The distinctive part, and the `feature`,
 * is the last column: every integrations page in this category lists logos,
 * and none of them tells you what each integration cannot see.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { CapabilityPage } from "@/components/marketing/capability";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "One policy, six control points",
  description:
    "The same rules at the hook, the gateway, the SDK, the MCP governor, LangGraph, and the CLI. Each one misses something.",
  path: "/control-points",
});

const POINTS = [
  {
    where: "Your coding agent",
    how: "Claude Code hooks",
    sees: ["The turn you submitted", "Each tool call before it runs", "Every tool result"],
    blind: "Anything that does not go through this harness, including a session in the vendor's cloud.",
    href: "/hooks",
  },
  {
    where: "Any language",
    how: "HTTP gateway",
    sees: ["Whatever you post to it", "One endpoint per surface", "Model traffic, if you proxy it"],
    blind: "Calls your code makes without asking it.",
    href: "/how-it-works",
  },
  {
    where: "Python",
    how: "The SDK",
    sees: ["Prompts and completions", "OpenAI, Anthropic, LiteLLM, LangChain", "Sync, async and streamed"],
    blind: "Tool calls. It patches model clients, so a tool the agent invokes directly never reaches it.",
    href: "/how-it-works",
  },
  {
    where: "Tool servers",
    how: "MCP governor",
    sees: ["The call and its arguments", "The schema it was approved under", "What the server sent back"],
    blind: "A server nobody pointed it at. An undeclared tool shows up the first time it is called.",
    href: "/mcp",
  },
  {
    where: "Graphs",
    how: "LangGraph tool node",
    sees: ["Each tool call in the run", "Retrieved documents", "Model input and output"],
    blind: "Nodes you did not wrap.",
    href: "/how-it-works",
  },
  {
    where: "CI and the terminal",
    how: "The CLI",
    sees: ["A repository, without running it", "A session transcript", "A policy, before it ships"],
    blind: "Anything already running. It reads and records. It does not stop a live call.",
    href: "/product",
  },
] as const;

export default function Page() {
  return (
    <CapabilityPage
      kicker="Enforcement"
      title={["One policy,", "six control points"]}
      lede="The same rules at the hook, the gateway, the SDK, the MCP governor, LangGraph, and the CLI. Each one misses something."
      docs="/docs/concepts"
      challenge={
        <p>One team uses LangGraph, one calls an API from Go, one runs Claude Code on a laptop.</p>
      }
      feature={{
        title: "What each one is blind to",
        lede: "What it sees, and what it cannot.",
        body: (
          <div className="cp-list mk-stagger">
            {POINTS.map((point) => (
              <article key={point.how} className="cp-item">
                <div className="cp-item-head">
                  <span className="cp-where">{point.where}</span>
                  <h3>{point.how}</h3>
                </div>
                <div className="cp-item-body">
                  <ul className="cp-sees">
                    {point.sees.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                  <p className="cp-blind">
                    <b>Blind to</b> {point.blind}
                  </p>
                  <Link href={point.href} className="cp-more">
                    More &rarr;
                  </Link>
                </div>
              </article>
            ))}
          </div>
        ) }}
      steps={[
        {
          title: "One engine behind all six",
          body: <p>Each one calls the same enforcer, against the same packs, and writes the same kind of record.</p>,
        },
        {
          title: "Write the rule once",
          body: <p>A rule you wrote for the gateway is already in force at the hook. You can add a binding point later without moving traffic.</p>,
        },
      ]}
      gaps={{
        title: "These six are not every place an agent can run",
        body: <p>Traffic that goes through none of them is ungoverned. The list is the doors that exist, not every door an agent can use.</p> }}
      related={["/hooks", "/mcp", "/runtime"]}
    />
  );
}
