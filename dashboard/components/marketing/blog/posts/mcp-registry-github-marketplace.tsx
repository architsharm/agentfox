import Link from "next/link";

import type { TocItem } from "@/components/marketing/blog/article";
import { InlineCTA, Takeaways, type FaqItem } from "@/components/marketing/blog/blocks";

export const toc: TocItem[] = [
  { id: "registry", label: "From the MCP Registry: ask AgentFox from any MCP client" },
  { id: "marketplace", label: "From the Marketplace: scan every pull request" },
  { id: "what", label: "What the scan finds" },
];

export const faq: FaqItem[] = [
  {
    q: "What does the AgentFox MCP server expose?",
    a: "Read-only tools over your AgentFox workspace: issues, agents, policies, simulations and checks. None of its tools changes what is blocked. It runs with uvx agentfox serve mcp and is listed on the official MCP Registry as io.github.architsharm/agentfox.",
  },
  {
    q: "Does the GitHub Action run my code?",
    a: "No. It reads the repository and never executes it, needs no account and no key, and fails the check only for the finding classes you name in fail-on.",
  },
  {
    q: "Does the registry entry update with releases?",
    a: "Yes. The release workflow publishes each tagged version to the MCP Registry after the PyPI release, so the registry always points at the version on PyPI.",
  },
];

export function Body() {
  return (
    <>
      <Takeaways
        items={[
          "uvx agentfox serve mcp, or the registry entry io.github.architsharm/agentfox, gives any MCP client read-only tools over your workspace.",
          "uses: architsharm/agentfox@main in a workflow scans every pull request for lethal trifectas, ungoverned model calls and poisoned skills, offline.",
          "Both are listed where the client already looks: the official MCP Registry and the GitHub Marketplace.",
        ]}
      />

      <h2 id="registry">From the MCP Registry: ask AgentFox from any MCP client</h2>
      <p>
        AgentFox is listed on the official MCP Registry as <code>io.github.architsharm/agentfox</code>.
        A client that reads the registry can install it from there; any other MCP client takes one
        line of config. The server speaks MCP over stdio and exposes read-only tools over your
        workspace: the open issues, the agents and their tools, the policies in force, simulations
        and the checks a call went through. None of its tools changes what is blocked, so giving it
        to an assistant is safe by construction.
      </p>
      <pre>{`{ "mcpServers": { "agentfox": { "command": "uvx", "args": ["agentfox", "serve", "mcp"] } } }`}</pre>
      <p>
        With the account key in the environment it reads your hosted workspace; without one it reads
        the local database. The questions that work well: which agent holds the most tools, what was
        held for a person this week, and which MCP tool changed since it was pinned. The{" "}
        <Link href="/docs/connect/mcp">MCP page</Link> has the server, and the Claude Code plugin
        starts it for you.
      </p>

      <h2 id="marketplace">From the Marketplace: scan every pull request</h2>
      <p>
        The Action is on the GitHub Marketplace as <strong>AgentFox scan</strong>, under Security and
        Code quality. Two lines in a workflow, and every pull request is read for the three things a
        review misses because each piece looks fine on its own:
      </p>
      <pre>{`- uses: actions/checkout@v4
- uses: architsharm/agentfox@main
  with:
    fail-on: trifecta,skills`}</pre>
      <p>
        It reads the repository and never runs it, needs no account and no key, and only fails the
        check for the classes you name in <code>fail-on</code>. Everything else is reported and
        allowed, so it can sit on a repository from the first day without blocking anyone.
      </p>

      <h2 id="what">What the scan finds</h2>
      <ul>
        <li>
          <strong>Lethal trifectas.</strong> One agent that reads private data, reads untrusted
          content and can send something out, across its own tools, the MCP servers it loads and the
          skills it installs. The <Link href="/blog/lethal-trifecta-ai-agents">lethal trifecta post</Link>{" "}
          shows the shape in real repositories.
        </li>
        <li>
          <strong>Ungoverned model calls.</strong> A model client called from code no guardrail sees.
        </li>
        <li>
          <strong>Poisoned skills.</strong> Instructions planted in a skill or a tool description, and
          declared danger in what a skill asks to run.
        </li>
      </ul>
      <p>
        The same scan runs from the command line as <code>agentfox scan</code>, which is the first
        thing in the README. The Action is that command, on every pull request, with a result you can
        make required.
      </p>

      <InlineCTA
        title="Add the scan to one repository"
        body="Two lines in a workflow. Read-only, offline, no account. The first run tells you what each agent in the repository can reach."
        href="/integrations/mcp"
        label="MCP with AgentFox: scan, pin, govern"
      />
    </>
  );
}
