/**
 * The docs sidebar. Marketing pages describe the product. This list is where
 * the commands live, so a page and the menu cannot drift.
 */

export type DocLink = { href: string; label: string };

export type DocSection = { heading: string; items: DocLink[] };

export const DOC_NAV: DocSection[] = [
  {
    heading: "Start",
    items: [
      { href: "/docs", label: "Getting started" },
      { href: "/docs/commands", label: "Commands" },
      { href: "/docs/connect", label: "Where it connects" },
      { href: "/docs/self-host", label: "Self-hosting" },
      { href: "/docs/harness", label: "Harness" },
    ],
  },
  {
    heading: "Product",
    items: [
      { href: "/docs/discovery", label: "Discovery" },
      { href: "/docs/access", label: "Access control" },
      { href: "/docs/runtime", label: "Runtime" },
      { href: "/docs/hooks", label: "Coding agents" },
      { href: "/docs/mcp", label: "MCP" },
      { href: "/docs/control-points", label: "Control points" },
      { href: "/docs/test", label: "Test" },
      { href: "/docs/evidence", label: "Audit trail" },
      { href: "/docs/compliance", label: "Compliance" },
    ],
  },
  {
    heading: "Help",
    items: [
      { href: "/docs/benchmarks", label: "Benchmarks" },
      { href: "/docs/limits", label: "Limits" },
      { href: "/docs/support", label: "Before you file" },
    ],
  },
];

export const DOC_PAGES: { href: string; title: string; description: string }[] = [
  {
    href: "/docs",
    title: "Getting started",
    description: "Install AgentFox, scan a repository, and run the offline demo.",
  },
  {
    href: "/docs/commands",
    title: "Commands",
    description: "The CLI grouped by what you are trying to do.",
  },
  {
    href: "/docs/connect",
    title: "Where it connects",
    description: "The calls that check model traffic, tool calls, and retrieval.",
  },
  {
    href: "/docs/self-host",
    title: "Self-hosting",
    description: "Render, Docker Compose, or the gateway as a Python app.",
  },
  {
    href: "/docs/harness",
    title: "Harness",
    description: "Skills, slash commands, and a read-only MCP server for a coding agent.",
  },
  {
    href: "/docs/discovery",
    title: "Discovery",
    description: "Scan a repository, a laptop session, and MCP servers.",
  },
  {
    href: "/docs/access",
    title: "Access control",
    description: "Declare what each tool does before the agent runs.",
  },
  {
    href: "/docs/runtime",
    title: "Runtime",
    description: "Lint a policy, watch it in observe, then turn enforcement on.",
  },
  {
    href: "/docs/hooks",
    title: "Coding agents",
    description: "Install the Claude Code hooks and keep the check already running.",
  },
  {
    href: "/docs/mcp",
    title: "MCP",
    description: "Record a tool server so a later change shows up at the call.",
  },
  {
    href: "/docs/control-points",
    title: "Control points",
    description: "The same rules at the hook, the gateway, the SDK, and the CLI.",
  },
  {
    href: "/docs/test",
    title: "Test",
    description: "Score a suite, probe a deployment, and replay traffic against a candidate policy.",
  },
  {
    href: "/docs/evidence",
    title: "Audit trail",
    description: "Export a decision record and check it without our code.",
  },
  {
    href: "/docs/compliance",
    title: "Compliance",
    description: "Read control status from what the agent did.",
  },
  {
    href: "/docs/benchmarks",
    title: "Benchmarks",
    description: "The published results, and where each one stops being a defence.",
  },
  {
    href: "/docs/limits",
    title: "Limits",
    description: "What is only as good as your declarations, and what is not built yet.",
  },
  {
    href: "/docs/support",
    title: "Before you file",
    description: "Commands to run before a GitHub issue, and what not to paste.",
  },
];
