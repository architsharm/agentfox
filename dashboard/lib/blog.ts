/**
 * The blog, and the one list of its posts.
 *
 * Same rule as lib/nav.ts and lib/docs.ts: the index page, the sitemap, the RSS
 * feed, llms.txt, each post's "keep reading" block and its structured data all
 * read this list, so a post cannot be published to one of them and forgotten by
 * the rest. A post's body lives in components/blog/posts/<slug>.tsx and is keyed
 * by the `Slug` type below, so a registered post with no body, or a body with no
 * registration, does not compile.
 *
 * `description` is the meta description and the card text: 120 to 160 characters,
 * because Google cuts at roughly 160 and a sentence cut mid-clause is the first
 * thing a stranger reads of us. `title` is the H1; `seoTitle` is the <title> when
 * the H1 is too long for one (the template adds " | AgentFox", 11 characters, and
 * Google truncates at roughly 60).
 *
 * Every number a post quotes is bound in benchmarks/claims.yaml, exactly as the
 * benchmark page's are, so a rerun that moves a number fails CI on the blog too.
 */

export const SLUGS = [
  "mcp-rug-pull-tool-poisoning",
  "prompt-injection-containment-not-detection",
  "claude-code-hooks-security",
  "continuous-red-teaming-ai-agents",
  "hidden-indirect-prompt-injection",
  "ai-agent-audit-trail",
] as const;

export type Slug = (typeof SLUGS)[number];

export type BlogPost = {
  slug: Slug;
  /** The H1. */
  title: string;
  /** The <title>, when the H1 is longer than about 48 characters. */
  seoTitle?: string;
  description: string;
  /** The topic chip on the card and the kicker on the post. */
  tag: "MCP security" | "Prompt injection" | "Coding agents" | "Red teaming" | "Audit and compliance";
  /** What a searcher types. The first is the phrase the post is built around. */
  keywords: string[];
  /** ISO dates. `updated` only when a post changed in substance. */
  published: string;
  updated?: string;
  readMinutes: number;
  /** The lead image: a real screen from the product or the site wherever possible. */
  image: { src: string; alt: string; width: number; height: number };
  /** Product and docs pages this post is the long-form argument for. */
  pillars: { href: string; label: string; why: string }[];
};

export const AUTHOR = { name: "The AgentFox team", url: "https://github.com/architsharm/agentfox" };

export const BLOG_POSTS: BlogPost[] = [
  {
    slug: "mcp-rug-pull-tool-poisoning",
    title: "MCP rug pulls: why approving an MCP server once is not enough",
    seoTitle: "MCP rug pulls and tool poisoning, explained",
    description:
      "An MCP server can pass review and change its tools a week later. How tool poisoning and rug pulls work, and how to catch drift at the moment of the call.",
    tag: "MCP security",
    keywords: [
      "MCP security",
      "MCP tool poisoning",
      "MCP rug pull",
      "Model Context Protocol security",
      "MCP server tool drift",
    ],
    published: "2026-10-06",
    readMinutes: 8,
    image: {
      src: "/blog/mcp-page.png",
      alt: "The AgentFox MCP security page: six MCP risks, four covered and two marked as gaps.",
      width: 1600,
      height: 900,
    },
    pillars: [
      { href: "/mcp", label: "MCP security", why: "The six MCP risks, and the two we do not cover." },
      { href: "/docs/guides/mcp", label: "MCP servers guide", why: "Scan configs, pin tools, govern calls." },
      { href: "/coverage", label: "Coverage", why: "Every failure mode we test, gaps included." },
    ],
  },
  {
    slug: "prompt-injection-containment-not-detection",
    title: "Prompt injection detection is a speed bump. Contain the tool call instead.",
    seoTitle: "Prompt injection defense: contain the tool call",
    description:
      "You will not detect every prompt injection. Capability grants, impact tiers and argument provenance stop the damaging tool call even when detection misses.",
    tag: "Prompt injection",
    keywords: [
      "prompt injection defense",
      "AI agent tool call authorization",
      "least privilege AI agents",
      "lethal trifecta",
      "prompt injection mitigation",
    ],
    published: "2026-10-06",
    readMinutes: 9,
    image: {
      src: "/product/refusal.png",
      alt: "A payments.transfer call refused with capability.denied: no capability grants this agent the requested tool and action.",
      width: 1600,
      height: 670,
    },
    pillars: [
      { href: "/benchmark", label: "Benchmarks", why: "The containment and AgentDojo results, losses included." },
      { href: "/grants", label: "Capability grants", why: "What each agent is allowed to do, written down first." },
      { href: "/docs/guides/contain-tool-calls", label: "Contain tool calls", why: "Declarations, grants and provenance, with code." },
    ],
  },
  {
    slug: "claude-code-hooks-security",
    title: "Which Claude Code hooks can actually stop a tool call",
    seoTitle: "Claude Code hooks for security: what can block",
    description:
      "Claude Code hooks are the only place a coding agent's tool call can be refused before it runs. Which hooks can block, which cannot, and a working baseline.",
    tag: "Coding agents",
    keywords: [
      "Claude Code hooks",
      "Claude Code security",
      "coding agent guardrails",
      "PreToolUse hook",
      "AI coding agent security",
    ],
    published: "2026-10-06",
    readMinutes: 7,
    image: {
      src: "/blog/hooks-page.png",
      alt: "The AgentFox coding agents page, showing which Claude Code hooks can stop a call.",
      width: 1600,
      height: 900,
    },
    pillars: [
      { href: "/hooks", label: "Coding agents", why: "Which hooks can stop a call, and which one cannot." },
      { href: "/docs/guides/coding-agents", label: "Coding agents guide", why: "Install the hooks and the coding-agent pack." },
      { href: "/control-points", label: "Control points", why: "The same policy at the hook, gateway and SDK." },
    ],
  },
  {
    slug: "continuous-red-teaming-ai-agents",
    title: "We attack our own AI agent every hour and publish what gets through",
    seoTitle: "Continuous red teaming for AI agents, in public",
    description:
      "A red-team report is out of date the day after it ships. How scheduled, opt-in probes against a deployed agent work, and why we publish our own misses.",
    tag: "Red teaming",
    keywords: [
      "AI agent red teaming",
      "continuous red teaming",
      "automated red teaming",
      "LLM red teaming in CI",
      "AI agent security testing",
    ],
    published: "2026-10-06",
    readMinutes: 8,
    image: {
      src: "/blog/live-page.png",
      alt: "The AgentFox live page: the demo agent probed every hour through the real enforcement path.",
      width: 1600,
      height: 900,
    },
    pillars: [
      { href: "/live", label: "Live", why: "Our own agent, attacked hourly, results unedited." },
      { href: "/coverage", label: "Coverage", why: "The failure modes we test, scored, gaps listed." },
      { href: "/docs/guides/live-probes", label: "Probe deployed agents", why: "Scheduled, opt-in attacks on your own agent." },
    ],
  },
  {
    slug: "hidden-indirect-prompt-injection",
    title: "Indirect prompt injection that hides: three techniques a keyword filter misses",
    seoTitle: "Hidden indirect prompt injection: 3 techniques",
    description:
      "Letter-spaced overrides, instructions hidden in markup, and persona jailbreaks. What they look like in a retrieved document, and how a detector catches them.",
    tag: "Prompt injection",
    keywords: [
      "indirect prompt injection",
      "prompt injection examples",
      "hidden prompt injection",
      "prompt injection detection",
      "RAG prompt injection",
    ],
    published: "2026-10-06",
    readMinutes: 8,
    image: {
      src: "/product/injection-blocked.png",
      alt: "A retrieved document carrying an instruction to transfer funds, blocked before it reached the model as indirect prompt injection.",
      width: 1600,
      height: 660,
    },
    pillars: [
      { href: "/runtime", label: "Runtime guardrails", why: "The prompt, the result and the document are all checked." },
      { href: "/benchmark", label: "Benchmarks", why: "How good detection is on its own, honestly." },
      { href: "/playground", label: "Playground", why: "Paste an injection and watch the verdict." },
    ],
  },
  {
    slug: "ai-agent-audit-trail",
    title: "An AI agent audit trail your auditor can check without your vendor",
    seoTitle: "AI agent audit trail: tamper-evident, checkable",
    description:
      "A log the vendor can rewrite is not evidence. How a hash-chained audit trail, signed checkpoints and a standalone verifier turn agent decisions into proof.",
    tag: "Audit and compliance",
    keywords: [
      "AI agent audit trail",
      "AI audit log",
      "tamper-evident logging",
      "EU AI Act record-keeping",
      "AI compliance evidence",
    ],
    published: "2026-10-06",
    readMinutes: 8,
    image: {
      src: "/blog/evidence-page.png",
      alt: "The AgentFox evidence and audit page: every allowed and blocked call recorded in a chain you can verify.",
      width: 1600,
      height: 900,
    },
    pillars: [
      { href: "/evidence", label: "Evidence and audit", why: "An audit trail you can check without our code." },
      { href: "/frameworks", label: "Compliance", why: "EU AI Act, NIST, OWASP and ATLAS, mapped as drafts." },
      { href: "/docs/guides/audit-evidence", label: "Prove it to an auditor", why: "The report, evidence packages, the verifier." },
    ],
  },
];

const BY_SLUG = new Map(BLOG_POSTS.map((p) => [p.slug, p]));

export function getPost(slug: string): BlogPost | undefined {
  return BY_SLUG.get(slug as Slug);
}

/** Newest first; ties keep registry order, which is the editorial order. */
export function postsByDate(): BlogPost[] {
  return [...BLOG_POSTS].sort((a, b) => b.published.localeCompare(a.published));
}

/**
 * Up to `n` other posts, same tag first. A reader who finished an MCP post is
 * likelier to want the other MCP post than the newest one.
 */
export function relatedPosts(post: BlogPost, n = 3): BlogPost[] {
  const others = postsByDate().filter((p) => p.slug !== post.slug);
  const same = others.filter((p) => p.tag === post.tag);
  const rest = others.filter((p) => p.tag !== post.tag);
  return [...same, ...rest].slice(0, n);
}

export function blogPath(slug: string): string {
  return `/blog/${slug}`;
}

/** "6 October 2026": the site is en-GB, and an unambiguous date beats 10/06. */
export function formatDate(iso: string): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}
