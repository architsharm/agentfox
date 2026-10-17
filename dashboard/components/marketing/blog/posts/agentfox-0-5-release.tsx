import Link from "next/link";

import type { TocItem } from "@/components/marketing/blog/article";
import { InlineCTA, Takeaways, type FaqItem } from "@/components/marketing/blog/blocks";
import { Code } from "@/components/docs/blocks";

export const toc: TocItem[] = [
  { id: "up", label: "agentfox up: one command to a governed project" },
  { id: "multi-agent", label: "Multi-agent systems, scanned as their agents" },
  { id: "validators", label: "About seventy built-in validators" },
  { id: "unicode-tags", label: "Hidden text in Unicode tags" },
  { id: "coding-agents", label: "Coding agents that keep their work" },
  { id: "open-core", label: "Open core and AgentFox Enterprise" },
  { id: "upgrade", label: "Upgrading" },
];

export const faq: FaqItem[] = [
  {
    q: "How do I upgrade to AgentFox 0.5?",
    a: "Run pip install -U agentfox. Coding-agent users should then rerun agentfox admin hooks install --write to pick up the new Stop hook. Self-hosted deployments pull the 0.5.0 images. Nothing in an existing policy needs changing.",
  },
  {
    q: "Does AgentFox support multi-agent systems?",
    a: "Yes. From 0.5 the repository scan reads each agent a codebase defines, the tools it is handed and which agent delegates to which, for the OpenAI Agents SDK, LangGraph, CrewAI, AutoGen and Google ADK, statically and before any traffic. Each agent is proposed with its own tools and grants.",
  },
  {
    q: "Is AgentFox still open source?",
    a: "Yes. Enforcement, containment, every detector and validator, custom rules, policy packs, retention and the audit trail are Apache-2.0 and run on their own. Compliance reporting, reviews and sign-off, the risk register, auditor evidence packages and fleet monitoring are in a source-available enterprise package under the Business Source License 1.1, free in production for one workspace with up to four agents.",
  },
  {
    q: "What is agentfox up?",
    a: "A guided setup command. It scans your repository, asks where AgentFox should run and how strict to start, and then wires up the hooks, the SDK, the gateway, your tools and MCP servers and the dashboard. It starts in observe mode, so nothing is blocked until you choose to enforce.",
  },
];

export function Body() {
  return (
    <>
      <Takeaways
        items={[
          <>
            <code>agentfox up</code> takes a project from <code>pip install</code> to governed,
            watching in observe mode, with one command and recommended answers to every
            question.
          </>,
          "A repository with several agents is now scanned as several agents: each with its own tools, joined by who delegates to whom, before it has handled a single request.",
          "About seventy validators ship as native code, a new detector catches instructions hidden in invisible Unicode, and the core stays Apache-2.0.",
        ]}
      />

      <p>
        AgentFox 0.5 is out. Most of it is about the first hour: getting from an agent you
        already have to an agent whose tool calls are checked, without reading the whole
        documentation first. The full list is in the{" "}
        <a href="https://github.com/architsharm/agentfox/blob/main/CHANGELOG.md">changelog</a>.
      </p>

      <h2 id="up">agentfox up: one command to a governed project</h2>
      <Code>{`pip install -U agentfox
agentfox up`}</Code>
      <p>
        <code>up</code> scans the repository and then asks three things: where AgentFox runs
        (on this machine; on your own server, either started here with Docker Compose or one
        that already exists; or AgentFox Cloud), what to cover, and how strict to start. Then
        it does the work. It installs the Claude Code and Codex hooks, adds{" "}
        <code>agentfox.auto()</code> to your entry point, sets up the gateway environment for
        any other language, declares the tools it found (inferring each one&apos;s impact, and
        never overwriting a declaration you wrote), registers your MCP servers and opens the
        dashboard on the scan.
      </p>
      <p>
        Every question has a recommended answer, and <code>--yes</code> takes them all. It
        starts in <strong>observe</strong> mode by default, so on day one nothing is blocked:
        you see what <em>would</em> have been, and switch to enforce when the verdicts look
        right. Run it again later and it only changes what is new.
      </p>
      <p>
        We ran it end to end, on a sample project, locally, against a production-mode team
        server, through Cloud and as a Compose stack, and fixed what broke. A set-up agent now
        works on its first call instead of being refused by default-deny; a busy port is named
        before Docker starts; a second run no longer records the same scan twice.
      </p>

      <h2 id="multi-agent">Multi-agent systems, scanned as their agents</h2>
      <p>
        Until now, a repository with an orchestrator and four sub-agents came out of a scan as
        one agent holding every tool any of them used. That is the wrong shape for
        least privilege: the research agent should not hold the refund tool because the billing
        agent does.
      </p>
      <p>
        The scan now reads each agent the code defines, the tools it is handed and which agent
        hands work to which: OpenAI Agents SDK handoffs and <code>as_tool</code>, LangGraph
        supervisors, swarms and <code>StateGraph</code> agent nodes, CrewAI crews and
        delegation, AutoGen teams and group chats, and Google ADK <code>sub_agents</code>. It
        does this statically, from the code, before the system has handled a request.
      </p>
      <p>
        Each agent is proposed with its own tools, joined by the delegation edges the code
        declares. The guardrail map shows the sub-agents and the agent that calls each one, a
        policy applied to an orchestrator can be applied to its sub-agents in one step, and the
        whole system can be added with one <strong>Add all</strong>.{" "}
        <code>agentfox scan --json</code> gains <code>agents</code> and{" "}
        <code>agent_edges</code> for anything you build on top.
      </p>

      <InlineCTA
        title="Scan your own repository"
        body="See which agents, tools and MCP servers your code defines, and what each one could do, before anything runs."
        href="/docs/guides/scan-a-repo"
        label="Scan a repo"
        secondary={{ href: "/docs/quickstart", label: "Quickstart" }}
      />

      <h2 id="validators">About seventy built-in validators</h2>
      <p>
        We ported about seventy checks from the Guardrails AI validator hub (Apache-2.0) as
        native code, so none of them needs its own install: system-prompt leaks, forbidden SQL
        and unknown columns, unsafe HTML, internal domains, fuzzy word lists, drug names, price
        quotes, format checks, local classifiers for jailbreaks, toxicity and gibberish, and
        LLM judges routed through the judgment tier.
      </p>
      <p>
        In the dashboard, pick one under <strong>Policies → Add rule → Use a built-in
        check</strong>, give it its settings and try it on a sample. It is watched and
        enforced like any other rule. If you already have a Guardrails AI guard, importing it
        now maps each validator onto its port with the same settings. Your own validators
        register through the <code>agentfox.validators</code> entry point.
      </p>

      <h2 id="unicode-tags">Hidden text in Unicode tags</h2>
      <p>
        A new default detector, <code>unicode.tags</code>, catches instructions hidden in
        Unicode tag characters: invisible to a person, read by many models. It runs on every
        surface and the injection rules you already have act on it. How the technique works
        and how the detector avoids flagging the flags of England, Scotland and Wales is in{" "}
        <Link href="/blog/ascii-smuggling-unicode-tag-prompt-injection">
          ASCII smuggling: prompt injection you cannot see
        </Link>
        .
      </p>

      <h2 id="coding-agents">Coding agents that keep their work</h2>
      <p>
        The coding-agent hook has always refused dangerous commands. In 0.5 it also catches a
        coding agent that is about to lose work it already got right: tearing
        down a deployment after a check passed, opening a damaged database before copying it,
        leaving a service the task needs attached to the session, or answering one question
        when the task asked for all of them. Each policy intervenes at most once or twice per
        session. The Claude Code adapter now binds <strong>Stop</strong>, so a refusal keeps
        the agent working with the reason as its next instruction.
      </p>

      <h2 id="open-core">Open core and AgentFox Enterprise</h2>
      <p>
        The repository is now an Apache-2.0 open core plus a source-available enterprise
        package. Everything that decides whether a call happens stays open: enforcement,
        containment, every detector and validator, custom rules, policy packs, retention and
        legal holds, and the audit trail. The enterprise package holds the compliance and
        oversight layer: compliance status, reviews and sign-off, the risk register and board
        view, auditor evidence packages, fleet monitoring with Slack alerts, and external
        access checks.
      </p>
      <p>
        Enterprise is under the Business Source License 1.1. It is free in production for one
        workspace with up to four agents, and each release becomes Apache-2.0 three years after
        it ships. The open core never imports it, a contract in CI enforces that, and the open
        core&apos;s test suite runs without it. The details are on the{" "}
        <Link href="/pricing">pricing page</Link>.
      </p>

      <h2 id="upgrade">Upgrading</h2>
      <Code>{`pip install -U agentfox
agentfox admin hooks install --write   # coding agents: picks up the Stop hook`}</Code>
      <p>
        Self-hosted deployments pull the <code>0.5.0</code> images. Nothing in an existing
        policy needs changing; the new detector reports through the injection rules you already
        have. If you would rather try it before installing anything, the{" "}
        <Link href="/playground">playground</Link> needs no account.
      </p>
    </>
  );
}
