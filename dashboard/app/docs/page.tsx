import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, NextSteps, TaskTable } from "@/components/docs/blocks";
import { DOC_PAGES } from "@/lib/docs";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "AgentFox documentation",
  description:
    "Containment for AI agents: what an agent may do is decided by declarations, grants and where each argument came from. See, watch, contain, prove.",
  path: "/docs",
});

const AREAS: {
  name: string;
  question: string;
  items: { what: string; run: string; href: string }[];
}[] = [
  {
    name: "See",
    question: "What agents, tools and servers do you already have?",
    items: [
      { what: "Inventory a repository: model calls, tools, MCP servers, the lethal trifecta", run: "agentfox scan", href: "/docs/guides/scan-a-repo" },
      { what: "First look at this machine, including local AI-tool sessions", run: "agentfox scan --sessions", href: "/docs/guides/scan-a-repo" },
      { what: "MCP servers: reach, version pinning, auth, tool descriptions", run: "agentfox scan mcp", href: "/docs/guides/mcp" },
      { what: "Agent skills: planted instructions and declared danger", run: "agentfox scan skills", href: "/docs/guides/scan-a-repo" },
      { what: "Shadow and unowned agents seen in traffic", run: "agentfox agents list", href: "/docs/app/agents" },
    ],
  },
  {
    name: "Contain",
    question: "What may each agent do, with which values, from which sources?",
    items: [
      { what: "Tool permissions: declare impact, grant with argument limits", run: "agentfox permit grant", href: "/docs/guides/contain-tool-calls" },
      { what: "Learned permissions: grants drafted from recorded calls, approved by a person", run: "agentfox policy proposals from-traffic", href: "/docs/guides/contain-tool-calls" },
      { what: "Provenance: refuse untrusted values in irreversible calls", run: "agentfox declare tool", href: "/docs/concepts#provenance" },
      { what: "Blast radius: what an agent reaches, and what a SQL or shell call would do", run: "agentfox agents lineage", href: "/docs/guides/contain-tool-calls" },
      { what: "Approvals for escalated calls, and the kill switch", run: "agentfox agents quarantine", href: "/docs/guides/approvals" },
      { what: "Loop and budget limits on a run", run: "agentfox policy effective", href: "/docs/reference/config#budgets" },
    ],
  },
  {
    name: "Screen",
    question: "Does the text itself look like an attack, a secret or personal data?",
    items: [
      { what: "Detectors on nine surfaces: injection, PII, secrets, safety, schema", run: "agentfox doctor", href: "/docs/reference/detectors" },
      { what: "Tune them: feedback, suppressions, simulate, canary", run: "agentfox policy simulate", href: "/docs/guides/tuning" },
    ],
  },
  {
    name: "Ground",
    question: "Is the answer inside what the agent knows, for someone allowed to see it?",
    items: [
      { what: "Answerability: a knowledge boundary and forced abstention", run: "agentfox declare boundary", href: "/docs/guides/rag" },
      { what: "Entitlement: what each end user may retrieve", run: "agentfox permit user", href: "/docs/guides/rag" },
      { what: "Sources: authority tiers and freshness", run: "agentfox declare source", href: "/docs/guides/rag" },
    ],
  },
  {
    name: "Prove",
    question: "Can you show someone else what happened, and that the controls hold?",
    items: [
      { what: "One-page summary for whoever signs off", run: "agentfox report", href: "/docs/guides/audit-evidence" },
      { what: "Tamper-evident audit chain", run: "agentfox report verify", href: "/docs/guides/audit-evidence" },
      { what: "Evidence package an auditor verifies without you", run: "agentfox report evidence", href: "/docs/guides/audit-evidence" },
      { what: "Compliance posture (draft mappings)", run: "agentfox report status", href: "/docs/guides/audit-evidence" },
      { what: "Red team the deployed configuration", run: "agentfox test redteam", href: "/docs/guides/red-team-and-evals" },
      { what: "Eval suites and a CI regression gate", run: "agentfox test gate", href: "/docs/guides/red-team-and-evals" },
    ],
  },
];

export default function DocsOverview() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Start</p>
      <h1>AgentFox documentation</h1>
      <p className="docs-lede">
        AgentFox decides what an AI agent may do from what you declared, what you granted, and
        where each argument came from, and records every decision so you can prove it later.
      </p>

      <p>
        Most agent-security tools are detectors: they read the text going into and out of a
        model and try to recognise an attack. A detector that misses lets the action through.
        AgentFox starts from the other end. Each tool carries a declared impact
        (read, write, high impact, irreversible), each agent holds explicit grants with
        argument limits, and every argument carries the <Link href="/docs/concepts#provenance">provenance</Link> of
        its value. An email whose recipient was copied out of a web page is refused because
        of where the address came from, whether or not anything recognised the page as
        hostile. Default deny means a tool nobody granted is refused on the first call.
      </p>
      <p>
        Detectors are still there, as a second layer: injection, personal data, secrets and
        unsafe content on every surface a request touches. They ship in observe mode, they
        raise the cost of an attack, and the product is built so that their failing is
        survivable. Containment was measured with every detector switched off; the numbers,
        and what they cost in escalated legitimate work, are on{" "}
        <Link href="/docs/benchmarks">Benchmarks</Link>. What it does not do yet is on{" "}
        <Link href="/docs/limits">Limits</Link>.
      </p>

      <h2>The path: see, watch, contain, prove</h2>
      <p>
        Four steps, in this order. Each is one command or one line, and each has a guide.
        The <Link href="/docs/quickstart">Quickstart</Link> walks all four against a sample
        agent in about ten minutes.
      </p>
      <table>
        <thead>
          <tr>
            <th>Step</th>
            <th>What you get</th>
            <th>Guide</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>
              <b>See</b>
              <br />
              <code>agentfox scan</code>
            </td>
            <td>
              A static read of the repository: every model call site and whether it is
              governed, every tool and MCP server, and each place where one agent can read
              private data, read untrusted content and send data out (the lethal trifecta).
              Nothing leaves the machine.
            </td>
            <td>
              <Link href="/docs/guides/scan-a-repo">Audit a repository</Link>
            </td>
          </tr>
          <tr>
            <td>
              <b>Watch</b>
              <br />
              <code>{`agentfox.auto(mode="observe", intent="…")`}</code>
            </td>
            <td>
              One line at your entry point. Every model call and every tool call the model
              asks for is traced, checked and recorded. In observe mode nothing is refused;
              you get the list of what would have been.
            </td>
            <td>
              <Link href="/docs/guides/python-auto">One line in Python</Link>
            </td>
          </tr>
          <tr>
            <td>
              <b>Contain</b>
              <br />
              <code>agentfox policy proposals from-traffic</code>
            </td>
            <td>
              Tool declarations and grants drafted from the calls the agent actually made,
              with limits read only from clean calls. A person approves each one; nothing
              widens on its own. Or write them by hand with <code>agentfox permit grant</code>{" "}
              and <code>agentfox declare tool</code>.
            </td>
            <td>
              <Link href="/docs/guides/contain-tool-calls">Contain tool calls</Link>
            </td>
          </tr>
          <tr>
            <td>
              <b>Prove</b>
              <br />
              <code>agentfox report</code>
            </td>
            <td>
              One page for whoever signs off: what ran, what was contained and why, what
              observe mode would have stopped. The same page opens every evidence package,
              alongside a hash chain an auditor re-derives with a standalone script.
            </td>
            <td>
              <Link href="/docs/guides/audit-evidence">Prove it to an auditor</Link>
            </td>
          </tr>
        </tbody>
      </table>
      <p>No agent of your own yet? The offline demo needs nothing but the install:</p>
      <Code>{`pip install agentfox
agentfox init && agentfox demo`}</Code>
      <p>
        <code>init</code> creates a local database and loads the controls and policy packs.{" "}
        <code>demo</code> runs a thirteen-step walkthrough against three seeded agents in
        about five seconds. Use a scratch state directory for it; see{" "}
        <Link href="/docs/quickstart#demo">Quickstart</Link>.
      </p>

      <h2>What you can do</h2>
      <p>
        Five capability areas. Containment is the one that holds when the others miss, so it
        is the one to configure first.
      </p>
      {AREAS.map((area) => (
        <section key={area.name}>
          <h3 id={area.name.toLowerCase()}>{area.name}</h3>
          <p>{area.question}</p>
          <TaskTable rows={area.items.map((i) => ({ task: i.what, run: i.run, href: i.href }))} />
        </section>
      ))}

      <h2>Pick your integration</h2>
      <p>
        The same policy and the same decision record, bound wherever your agent already
        runs. Each place sees a different surface, so connecting one does not cover the
        others. <Link href="/docs/concepts#control-points">Control points</Link> lists what
        each one sees.
      </p>
      <table>
        <thead>
          <tr>
            <th>Your agent is</th>
            <th>Use</th>
            <th>What it governs</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Python, any framework that calls OpenAI, Anthropic, LiteLLM or LangChain</td>
            <td>
              <Link href="/docs/guides/python-auto">
                <code>agentfox.auto()</code>
              </Link>
            </td>
            <td>
              Every model call in the process, and every tool call in a response before your
              code runs it. Not the OpenAI Responses API, and not tools your code calls
              without the model asking.
            </td>
          </tr>
          <tr>
            <td>A LangGraph graph</td>
            <td>
              <Link href="/docs/guides/langgraph">
                <code>AgentFoxGuard</code> node wrappers
              </Link>
            </td>
            <td>
              Retrieval, model and tool nodes. An escalation becomes LangGraph&apos;s own{" "}
              <code>interrupt()</code>.
            </td>
          </tr>
          <tr>
            <td>An MCP client or server</td>
            <td>
              <Link href="/docs/guides/mcp">
                <code>agentfox scan mcp</code> and the MCP governor
              </Link>
            </td>
            <td>
              Server reach and pinning before anything runs; at call time, tool digests (a
              server that changed after review) and results checked as untrusted input.
            </td>
          </tr>
          <tr>
            <td>A coding agent (Claude Code)</td>
            <td>
              <Link href="/docs/guides/coding-agents">
                <code>agentfox admin hooks install</code>
              </Link>
            </td>
            <td>
              The prompt, each tool call before it runs, and each result. On this machine
              only.
            </td>
          </tr>
          <tr>
            <td>Any language</td>
            <td>
              <Link href="/docs/guides/gateway">
                <code>agentfox serve</code>, the gateway
              </Link>
            </td>
            <td>
              A drop-in OpenAI or Anthropic endpoint, and{" "}
              <code>POST /v1/guard/tool_call</code> to ask about one call before you run it.
            </td>
          </tr>
        </tbody>
      </table>
      <Callout kind="note" title="Observe first">
        Nothing above blocks model traffic until you run{" "}
        <code>agentfox policy enforce baseline</code>. The one exception is deliberate:
        the <code>tool-containment</code> pack enforces from <code>agentfox init</code>,
        because a missing grant or an untrusted value in an irreversible call is a fact,
        not a guess. <code>auto(mode=&quot;observe&quot;)</code> records even those without
        raising.
      </Callout>

      <h2>Every page</h2>
      <ul>
        {DOC_PAGES.map((page) => (
          <li key={page.href}>
            <Link href={page.href}>{page.title}</Link>
            {page.description ? <span>: {page.description}</span> : null}
          </li>
        ))}
      </ul>

      <NextSteps
        items={[
          { href: "/docs/quickstart", label: "Quickstart", why: "scan, watch, contain and report a sample agent in ten minutes" },
          { href: "/docs/concepts", label: "Concepts", why: "the vocabulary every other page uses" },
          { href: "/docs/install", label: "Install and configure", why: "extras, where state lives, agentfox.toml" },
        ]}
      />
    </article>
  );
}
