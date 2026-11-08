/**
 * The docs sidebar, and the one list of docs pages. A page and the menu cannot drift
 * because there is only this list. The order is the order a reader walks: start, connect
 * an agent, then the five jobs (discover, govern, protect, test, prove), then deploy.
 * Every page gets a previous/next link from its place here (components/docs/pager.tsx).
 *
 * Task pages stay short: a few steps, a screenshot per step, one short command at most.
 * Flags, full YAML and every route live in Reference, which is generated from the code
 * where it can be (scripts/gen/docs_reference.py).
 */
export type DocLink = { href: string; label: string; description?: string };
export type DocSection = { heading: string; items: DocLink[] };

export const DOC_NAV: DocSection[] = [
  {
    heading: "Get started",
    items: [
      { href: "/docs", label: "What is AgentFox", description: "What it does, in one screen." },
      { href: "/docs/quickstart", label: "Quickstart", description: "Connect a repository, test its agents, add guardrails." },
      { href: "/docs/quickstart/cli", label: "Quickstart without an account", description: "The same, on your machine only." },
      { href: "/docs/concepts", label: "Core concepts", description: "Agents, tools, access, guardrails, issues." },
    ],
  },
  {
    heading: "Connect your agent",
    items: [
      { href: "/docs/connect", label: "Pick your stack", description: "Which page to follow for your framework." },
      { href: "/docs/connect/python", label: "Python apps", description: "One line: agentfox.auto()." },
      { href: "/docs/connect/langgraph", label: "LangGraph", description: "Guard each node of a graph." },
      { href: "/docs/connect/litellm", label: "LiteLLM proxy", description: "Every agent behind the proxy, checked." },
      { href: "/docs/connect/mcp", label: "MCP servers", description: "Scan, pin and govern MCP tools." },
      { href: "/docs/connect/coding-agents", label: "Claude Code and Codex", description: "Hooks for coding agents." },
      { href: "/docs/connect/platforms", label: "Voice and hosted platforms", description: "Vapi, Retell, Copilot Studio, AgentCore." },
      { href: "/docs/connect/http", label: "Any language (HTTP)", description: "The proxy and the guard API." },
    ],
  },
  {
    heading: "Discover",
    items: [
      { href: "/docs/discover", label: "Map your agents", description: "Agents, tools and risky paths, found in your code." },
    ],
  },
  {
    heading: "Govern",
    items: [
      { href: "/docs/govern", label: "Tool access", description: "Which tools each agent may call, and with what." },
      { href: "/docs/govern/approvals", label: "Approvals and the kill switch", description: "Hold a call for a person; stop an agent." },
      { href: "/docs/govern/data-access", label: "Who may see what", description: "Per-user access to retrieved data." },
    ],
  },
  {
    heading: "Protect",
    items: [
      { href: "/docs/protect", label: "Guardrails", description: "Turn on checks; watch first, then block." },
      { href: "/docs/protect/custom-rules", label: "Custom rules", description: "Your own rules, business limits, imported policies." },
      { href: "/docs/protect/tuning", label: "Fix false positives", description: "When a guardrail blocks a real user." },
    ],
  },
  {
    heading: "Test",
    items: [
      { href: "/docs/test", label: "Attack tests", description: "Attack your agent before someone else does." },
      { href: "/docs/test/ci", label: "In CI and in production", description: "Fail the build on a regression; probe live agents." },
    ],
  },
  {
    heading: "Prove",
    items: [
      { href: "/docs/prove", label: "Traces and issues", description: "Every call, every check, and what needs a person." },
      { href: "/docs/prove/audit", label: "Audit evidence", description: "Reports and compliance mappings." },
      { href: "/docs/prove/integrations", label: "Send traces elsewhere", description: "OpenTelemetry, Langfuse, SIEM, webhooks." },
    ],
  },
  {
    heading: "Deploy",
    items: [
      { href: "/docs/self-host", label: "Self-host", description: "Docker Compose, Render, or a Python app." },
      { href: "/docs/production", label: "Production checklist", description: "Settings to check before real traffic." },
    ],
  },
  {
    heading: "Reference",
    items: [
      { href: "/docs/reference/cli", label: "CLI", description: "Every command and option." },
      { href: "/docs/reference/api", label: "HTTP API", description: "Every route." },
      { href: "/docs/reference/python", label: "Python SDK", description: "auto(), sessions, integrations." },
      { href: "/docs/reference/policies", label: "Policy language", description: "Rule schema, packs, modes." },
      { href: "/docs/reference/detectors", label: "Detectors and findings", description: "What each check looks for." },
      { href: "/docs/reference/config", label: "Configuration", description: "Environment variables and agentfox.toml." },
      { href: "/docs/reference/install", label: "Install options", description: "Extras, models, where state lives." },
      { href: "/docs/reference/owasp", label: "OWASP Agentic Top 10", description: "What is covered, partly covered, or not." },
      { href: "/docs/reference/migrate-from-llm-guard", label: "Coming from LLM Guard", description: "Each scanner and its equivalent." },
      { href: "/docs/benchmarks", label: "Benchmarks", description: "What was measured, and where it stops." },
      { href: "/docs/limits", label: "Limits", description: "What AgentFox does not do." },
    ],
  },
  {
    heading: "Help",
    items: [
      { href: "/docs/support", label: "Troubleshooting", description: "Common problems, and how to get help." },
    ],
  },
];

/** Every docs page, flat, in reading order: the sitemap, the pager, the overview. */
export const DOC_PAGES: { href: string; title: string; description: string; section: string }[] =
  DOC_NAV.flatMap((section) =>
    section.items.map((item) => ({
      href: item.href,
      title: item.label,
      description: item.description ?? "",
      section: section.heading,
    })),
  );
