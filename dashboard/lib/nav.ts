/**
 * The site's information architecture, in one place.
 *
 * Four things used to carry their own copy of it — the header, the footer,
 * `sitemap.ts` and `llms.txt` — and the failure mode was always the same:
 * a page was added and three of the four never heard about it. The
 * machine-readable test exists because that happened. This file makes the
 * drift impossible rather than detectable.
 *
 * Every entry carries a `note`. That is not decoration: in the header menu
 * the note is rendered under the label, so the menu itself explains the
 * product rather than making the reader open six pages to find out which one
 * they wanted. It is also what `llms.txt` publishes, so the description an
 * assistant reads and the description a person reads are the same sentence,
 * and neither can go stale without the other.
 */

export type NavItem = {
  label: string;
  href: string;
  /**
   * The menu line. Short on purpose — at ten items a sentence each, the
   * product panel was 583px of prose and read as a page rather than a menu.
   * Six or seven words; if it needs a comma it is probably too long.
   */
  note: string;
  /**
   * The fuller line, for llms.txt. An assistant deciding what to recommend
   * has room for a sentence where a menu does not, and this is the one place
   * the extra clause earns its keep. Falls back to `note`.
   */
  summary?: string;
  /** Sitemap hints. Omitted for anything that should not be indexed. */
  sitemap?: { changeFrequency: "weekly" | "monthly" | "yearly"; priority: number };
};

export type NavSection = {
  /**
   * Required. The first section used to be allowed to have none, which put two
   * unlabelled links above two labelled groups and read as a mistake — every
   * dropdown worth copying labels every group, including the first.
   */
  heading: string;
  /** Which column of the panel this section sits in. Defaults to 1. */
  column?: 1 | 2;
  items: NavItem[];
};

export type NavGroup = {
  /** The header button. */
  label: string;
  sections: NavSection[];
};

/**
 * The product menu.
 *
 * Grouped the way a reader's question is shaped, which is not the way the
 * codebase is shaped. "Where it runs" is the first question someone with an
 * agent has, and "what it checks" is the second; the six areas the product is
 * internally organised into are an implementation fact that helps nobody
 * choose a page.
 */
export const PRODUCT: NavGroup = {
  label: "Product",
  sections: [
    {
      heading: "Start here",
      column: 1,
      items: [
        {
          label: "Overview",
          href: "/product",
          note: "The control plane, one page",
          summary: "Find the agents you are running, decide what each one may do, block the rest, test it, and keep the record.",
          sitemap: { changeFrequency: "weekly", priority: 0.9 },
        },
        {
          label: "How it works",
          href: "/how-it-works",
          note: "What happens on a tool call",
          summary: "The prompt, the documents it read, whether the call was allowed, and the record left behind.",
          sitemap: { changeFrequency: "monthly", priority: 0.8 },
        },
      ],
    },
    {
      heading: "Where it binds",
      column: 1,
      items: [
        {
          label: "Coding agents",
          href: "/hooks",
          note: "Which hooks can stop a call",
          summary: "Claude Code has three hooks. Two can stop a call. One cannot, and this page says which.",
          sitemap: { changeFrequency: "weekly", priority: 0.9 },
        },
        {
          label: "MCP",
          href: "/mcp",
          note: "Tool poisoning and rug pulls",
          summary: "Approving an MCP server once is not enough. If a tool changes later, that shows up when it is called.",
          sitemap: { changeFrequency: "monthly", priority: 0.8 },
        },
        {
          label: "Control points",
          href: "/control-points",
          note: "One policy, six control points",
          summary: "The same rules at the hook, the gateway, the SDK, the MCP governor, LangGraph, and the CLI.",
          sitemap: { changeFrequency: "monthly", priority: 0.8 },
        },
      ],
    },
    {
      heading: "What it does",
      column: 2,
      items: [
        {
          label: "Discovery",
          href: "/discovery",
          note: "Every agent, tool, and server",
          summary: "In your repositories, and on laptops where they were never committed. If nobody owns one, it is listed.",
          sitemap: { changeFrequency: "monthly", priority: 0.8 },
        },
        {
          label: "Capability grants",
          href: "/grants",
          note: "What each agent is allowed to do",
          summary: "You write that down before the agent runs. A prompt cannot add to it.",
          sitemap: { changeFrequency: "monthly", priority: 0.8 },
        },
        {
          label: "Runtime guardrails",
          // Not /guardrails: middleware 308s that to the signed-in app, where
          // it has been a real page for longer than this one has existed.
          href: "/runtime",
          note: "The tool call is checked too",
          summary: "So are the prompt, the result, the document the agent read, and what it saves to memory.",
          sitemap: { changeFrequency: "monthly", priority: 0.8 },
        },
        {
          label: "Evidence and audit",
          href: "/evidence",
          note: "An audit trail you can check",
          summary: "Every time a call is allowed, and every time it is blocked. You can check the export without our code.",
          sitemap: { changeFrequency: "monthly", priority: 0.8 },
        },
        {
          label: "Compliance",
          // Not /compliance, for the same reason as /runtime above — and
          // /frameworks is the better URL anyway, because the page is about
          // seven of them.
          href: "/frameworks",
          note: "EU AI Act, NIST, OWASP, ATLAS",
          summary: "43 controls. You meet one because of what the agent did, not because someone filled in a form.",
          sitemap: { changeFrequency: "monthly", priority: 0.8 },
        },
      ],
    },
  ],
};

/**
 * The second dropdown.
 *
 * Named Resources because that is what this slot is called on every site a
 * visitor has already used, and a header is the one place to spend nothing on
 * originality — someone looking for a benchmark scans for the word they
 * expect. The differentiator keeps its name one level down, as the heading of
 * the group it belongs to.
 *
 * The playground is deliberately not in here. It is the thing we most want a
 * stranger to do and it needs no account, so burying it two interactions deep
 * was working against the only conversion this site has.
 */
export const RESOURCES: NavGroup = {
  label: "Resources",
  sections: [
    {
      heading: "Evidence",
      column: 1,
      items: [
        {
          label: "Coverage",
          href: "/coverage",
          note: "Red team coverage, gaps included",
          summary:
            "116 ways an agent can fail, scored against what AgentFox catches, and cut by cause: external, internal, autonomous, intrinsic. 105 executed against the running product nightly; the gaps are listed too.",
          sitemap: { changeFrequency: "weekly", priority: 0.8 },
        },
        {
          label: "Benchmarks",
          href: "/benchmark",
          note: "Results, including the losses",
          summary: "The published results, including the losses.",
          sitemap: { changeFrequency: "monthly", priority: 0.7 },
        },
        {
          label: "Compare",
          href: "/compare",
          note: "Where each one is ahead",
          summary: "Where a governance platform is ahead of us, and where a runtime tool is.",
          sitemap: { changeFrequency: "monthly", priority: 0.8 },
        },
      ],
    },
    {
      heading: "Project",
      column: 2,
      items: [
        {
          label: "Security",
          href: "/security",
          note: "What nobody else has checked",
          summary: "How to report a vulnerability, what the code enforces, and what nobody outside this project has checked.",
          sitemap: { changeFrequency: "yearly", priority: 0.4 },
        },
        {
          label: "Support",
          href: "/support",
          note: "No promised reply time",
          summary: "One person reads these. There is no promised reply time.",
          sitemap: { changeFrequency: "monthly", priority: 0.6 },
        },
      ],
    },
  ],
};

/**
 * Flat header links, after the two dropdowns.
 *
 * The playground first, because it is the one thing on this site a stranger
 * can do in ten seconds with no account, and it was previously three
 * interactions away inside a menu.
 */
export const FLAT: NavItem[] = [
  {
    label: "Playground",
    href: "/playground",
    note: "Red team it. No account",
    summary: "Red team a running agent in the browser, with no account. The verdict comes from the product.",
    sitemap: { changeFrequency: "monthly", priority: 0.8 },
  },
  {
    label: "Docs",
    href: "/docs",
    note: "Install and commands",
    summary: "Install AgentFox, and the commands for discovery, access control, runtime, hooks, and the audit trail.",
    sitemap: { changeFrequency: "weekly", priority: 0.8 },
  },
  {
    label: "Pricing",
    href: "/pricing",
    note: "Free to self-host, forever",
    summary: "Free to self-host, under Apache-2.0. The hosted preview is free, and nothing on this site is priced.",
    sitemap: { changeFrequency: "monthly", priority: 0.7 },
  },
];

/** Not in the header. Real pages all the same, reachable from the footer. */
export const SECONDARY: NavItem[] = [
  {
    label: "Legal",
    href: "/legal",
    note: "The hub for the two below",
    sitemap: { changeFrequency: "yearly", priority: 0.4 },
  },
  {
    label: "Privacy",
    href: "/privacy",
    note: "What the hosted demo stores",
    sitemap: { changeFrequency: "yearly", priority: 0.4 },
  },
  {
    label: "Terms",
    href: "/terms",
    note: "Terms for the hosted service",
    sitemap: { changeFrequency: "yearly", priority: 0.3 },
  },
];

export const GROUPS: NavGroup[] = [PRODUCT, RESOURCES];

/** The landing page, which belongs in the sitemap and in no menu. */
export const HOME: NavItem = {
  label: "AgentFox",
  href: "/",
          note: "What this is, in one idea",
          summary: "What AgentFox is, and the one idea it is built on: calls approach a capability check, most go through, one does not.",
  sitemap: { changeFrequency: "weekly", priority: 1 },
};

/** Every page, in one list. The thing four files used to each keep their own copy of. */
export const ALL_PAGES: NavItem[] = [
  HOME,
  ...GROUPS.flatMap((g) => g.sections.flatMap((s) => s.items)),
  ...FLAT,
  ...SECONDARY,
];

export const ALL_PATHS: string[] = ALL_PAGES.map((p) => p.href);
