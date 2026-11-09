import type { Metadata } from "next";
import Link from "next/link";

import { Cards, NextSteps } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "What is AgentFox",
  description:
    "AgentFox finds the AI agents in your code, decides which tools each may use, checks every call while it runs, attacks it before release, and records what happened.",
  path: "/docs",
});

const box = { fill: "var(--mk-surface)", stroke: "var(--mk-border-strong)", strokeWidth: 1.5 };
const line = { stroke: "var(--mk-border-strong)", strokeWidth: 1.5 };
const label = { fill: "var(--mk-text)", fontSize: 14, fontWeight: 600 };
const check = { fill: "var(--mk-accent-soft)", stroke: "var(--mk-accent)", strokeWidth: 1.5 };
const checkText = { fill: "var(--mk-accent)", fontSize: 11, fontWeight: 600 };

/** One box on the picture: a rounded rectangle with a centred label. */
function Node({ x, y, w, text }: { x: number; y: number; w: number; text: string }) {
  return (
    <g>
      <rect x={x} y={y} width={w} height={44} rx={8} style={box} />
      <text x={x + w / 2} y={y + 27} textAnchor="middle" style={label}>
        {text}
      </text>
    </g>
  );
}

/** The AgentFox check sitting on a line. */
function Check({ x, y }: { x: number; y: number }) {
  return (
    <g>
      <rect x={x - 34} y={y - 11} width={68} height={22} rx={11} style={check} />
      <text x={x} y={y + 4} textAnchor="middle" style={checkText}>
        AgentFox
      </text>
    </g>
  );
}

function WhereItSits() {
  return (
    <figure style={{ margin: "24px 0" }}>
      <svg
        viewBox="0 0 640 210"
        width="100%"
        role="img"
        aria-label="Your app sends a request to your agent. The agent calls a model and calls tools and data. AgentFox checks each of those three lines."
      >
        <line x1={130} y1={105} x2={230} y2={105} style={line} />
        <line x1={350} y1={98} x2={480} y2={44} style={line} />
        <line x1={350} y1={112} x2={480} y2={166} style={line} />
        <Node x={10} y={83} w={120} text="Your app" />
        <Node x={230} y={83} w={120} text="Agent" />
        <Node x={480} y={22} w={150} text="Model" />
        <Node x={480} y={144} w={150} text="Tools and data" />
        <Check x={180} y={105} />
        <Check x={415} y={71} />
        <Check x={415} y={139} />
      </svg>
      <figcaption style={{ fontSize: 14, color: "var(--mk-muted)" }}>
        AgentFox checks each line: what a user sends, what goes to and comes back from the model, and
        every tool call before it runs.
      </figcaption>
    </figure>
  );
}

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>What is AgentFox</h1>
      <p className="docs-lede">
        AgentFox keeps your AI agents to the job you gave them, without blocking real users.
      </p>
      <p>
        It reads your code and finds each agent, the model it uses and the tools it can call. You
        decide which tools each agent may use, and which calls a person must approve first. While your
        app runs, AgentFox checks every message, reply and tool call, and records what it decided. New
        guardrails start in Watch, so you see what they would stop before you switch them to Block.
      </p>

      <WhereItSits />

      <p>
        <Link href="/docs/quickstart">
          <strong>Start with the Quickstart</strong>
        </Link>
        : connect a repository, attack its agents and turn on guardrails in about five minutes. No
        account? Use the <Link href="/docs/quickstart/cli">Quickstart without an account</Link>.
      </p>

      <h2>The five jobs</h2>
      <Cards
        items={[
          {
            href: "/docs/discover",
            title: "Discover",
            text: "Find the agents in your code, the tools they reach, and risky paths between them.",
          },
          {
            href: "/docs/govern",
            title: "Govern",
            text: "Choose which tools each agent may call, with limits, and hold risky calls for a person.",
          },
          {
            href: "/docs/protect",
            title: "Protect",
            text: "Check messages, replies and tool calls as they happen. Watch first, then block.",
          },
          {
            href: "/docs/test",
            title: "Test",
            text: "Attack your agents before someone else does, on your machine and in CI.",
          },
          {
            href: "/docs/prove",
            title: "Prove",
            text: "Every call and every check is recorded, with reports you can hand to an auditor.",
          },
        ]}
      />

      <NextSteps
        items={[
          { href: "/docs/quickstart", label: "Quickstart", why: "connect a repository, test its agents, add guardrails" },
          { href: "/docs/quickstart/cli", label: "Quickstart without an account", why: "the same, on your machine only" },
          { href: "/docs/concepts", label: "Core concepts", why: "agents, tools, access, guardrails, issues" },
        ]}
      />
    </article>
  );
}
