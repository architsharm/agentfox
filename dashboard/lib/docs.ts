/**
 * The docs sidebar, and the one list of docs pages. Marketing pages describe the
 * product; this is where it is explained, command by command. A page and the menu
 * cannot drift because there is only this list.
 *
 * The order follows the path a team walks: see what you have, watch it run, contain
 * what it can do, prove it. Guides are scenarios with working code; Reference is
 * generated from the code where it can be (scripts/docs_reference.py).
 */

export type DocLink = { href: string; label: string; description?: string };

export type DocSection = { heading: string; items: DocLink[] };

export const DOC_NAV: DocSection[] = [
  {
    heading: "Start",
    items: [
      { href: "/docs", label: "Overview", description: "What AgentFox does, and the path through it." },
      { href: "/docs/quickstart", label: "Quickstart", description: "Scan, watch, contain and report in ten minutes." },
      { href: "/docs/concepts", label: "Concepts", description: "Agents, tools, grants, provenance, policies and findings." },
      { href: "/docs/install", label: "Install and configure", description: "Extras, where state lives, agentfox.toml." },
    ],
  },
  {
    heading: "Guides",
    items: [
      { href: "/docs/guides/scan-a-repo", label: "Audit a repository", description: "Inventory, the lethal trifecta, and a CI gate." },
      { href: "/docs/guides/monitoring", label: "Monitor connected sources", description: "Rescan repos, APIs and MCP servers on a schedule and on push." },
      { href: "/docs/guides/python-auto", label: "One line in Python", description: "agentfox.auto(): observe, then enforce." },
      { href: "/docs/guides/contain-tool-calls", label: "Contain tool calls", description: "Declarations, grants, provenance, learned permissions." },
      { href: "/docs/guides/langgraph", label: "LangGraph", description: "Guard the retrieval, model and tool nodes." },
      { href: "/docs/guides/mcp", label: "MCP servers", description: "Scan configs, pin tools, govern calls." },
      { href: "/docs/guides/coding-agents", label: "Coding agents", description: "Claude Code hooks and the coding-agent pack." },
      { href: "/docs/guides/gateway", label: "Any language: the gateway", description: "The proxy and the guard API over HTTP." },
      { href: "/docs/guides/rag", label: "Retrieval and answers", description: "Who may see what, and when to say I don't know." },
      { href: "/docs/guides/approvals", label: "Approvals and the kill switch", description: "Escalations, hand-offs, quarantine." },
      { href: "/docs/guides/business-rules", label: "Business rules", description: "Threshold ladders, and policy compiled from prose." },
      { href: "/docs/guides/red-team-and-evals", label: "Red team and evals in CI", description: "Probe the deployment; fail the build on regression." },
      { href: "/docs/guides/tuning", label: "Tune detectors", description: "Feedback, suppressions, simulate, canary." },
      { href: "/docs/guides/audit-evidence", label: "Prove it to an auditor", description: "The report, evidence packages, compliance." },
      { href: "/docs/guides/observability", label: "Traces and integrations", description: "OpenTelemetry, Langfuse, LangSmith, SIEM, webhooks." },
    ],
  },
  {
    heading: "Web app",
    items: [
      { href: "/docs/app", label: "Tour of the web app", description: "Sign in, workspaces, and where everything is." },
      { href: "/docs/app/start", label: "Start here and connect", description: "The checklist, GitHub repos, API tokens." },
      { href: "/docs/app/agents", label: "Agents", description: "Registry, risk, knowledge boundary, kill switch." },
      { href: "/docs/app/findings", label: "Findings", description: "What needs a person, and why." },
      { href: "/docs/app/traces", label: "Traces", description: "One request, every check, and why it was blocked." },
      { href: "/docs/app/policies", label: "Policies and tuning", description: "Rules, modes, simulation, canary, detector tuning." },
      { href: "/docs/app/approvals", label: "Approvals and escalation", description: "The queue a person works from." },
      { href: "/docs/app/access-and-sources", label: "Access control and sources", description: "End-user entitlement and verified sources." },
      { href: "/docs/app/evals", label: "Evaluation", description: "Suites, runs, SLOs and red-team campaigns." },
      { href: "/docs/app/compliance", label: "Compliance", description: "Controls, frameworks, evidence, board snapshot." },
      { href: "/docs/app/playground", label: "Playground", description: "Attack a live agent with no account." },
    ],
  },
  {
    heading: "Reference",
    items: [
      { href: "/docs/reference/cli", label: "CLI", description: "Every command and option, generated from the CLI." },
      { href: "/docs/reference/api", label: "HTTP API", description: "Every route, generated from the gateway." },
      { href: "/docs/reference/python", label: "Python SDK", description: "auto(), AgentFox, sessions, integrations." },
      { href: "/docs/reference/policies", label: "Policy language", description: "Rule schema, packs, modes, hierarchy." },
      { href: "/docs/reference/detectors", label: "Detectors and findings", description: "Surfaces, detectors, finding types." },
      { href: "/docs/reference/config", label: "Configuration", description: "Environment variables and agentfox.toml." },
    ],
  },
  {
    heading: "Operate",
    items: [
      { href: "/docs/self-host", label: "Self-hosting", description: "Docker Compose, Render, or a Python app." },
      { href: "/docs/harness", label: "Claude Code harness", description: "Skills, slash commands and a read-only MCP server." },
      { href: "/docs/benchmarks", label: "Benchmarks", description: "What was measured, and where each result stops." },
      { href: "/docs/limits", label: "Limits", description: "What is only as good as your declarations." },
      { href: "/docs/support", label: "Support", description: "What to run before you file an issue." },
    ],
  },
];

/** Every docs page, flat: for the overview's index and anything that lists pages. */
export const DOC_PAGES: { href: string; title: string; description: string }[] = DOC_NAV.flatMap(
  (section) =>
    section.items.map((item) => ({
      href: item.href,
      title: item.label,
      description: item.description ?? "",
    })),
);
