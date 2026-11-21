/**
 * The blog, and the one list of its posts.
 *
 * Same rule as lib/marketing/nav.ts and lib/docs/pages.ts: the index page, the sitemap, the RSS
 * feed, llms.txt, each post's "keep reading" block and its structured data all
 * read this list, so a post cannot be published to one of them and forgotten by
 * the rest. A post's body lives in components/marketing/blog/posts/<slug>.tsx and is keyed
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
  "ai-agent-guardrail-latency",
  "agentfox-0-5-release",
  "ascii-smuggling-unicode-tag-prompt-injection",
  "mcp-rug-pull-tool-poisoning",
  "prompt-injection-containment-not-detection",
  "claude-code-hooks-security",
  "continuous-red-teaming-ai-agents",
  "hidden-indirect-prompt-injection",
  "ai-agent-audit-trail",
  "llm-guard-vs-agentfox-agentdojo",
  "lethal-trifecta-ai-agents",
  "security-questionnaire-prompt-injection",
  "least-privilege-ai-agents-tool-permissions",
  "mcp-server-security-checklist",
  "red-team-your-own-ai-agent",
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
  tag:
    | "MCP security"
    | "Prompt injection"
    | "Coding agents"
    | "Red teaming"
    | "Audit and compliance"
    | "Release notes"
    | "Benchmarks";
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
    slug: "security-questionnaire-prompt-injection",
    title: "How to answer \u201chow do you prevent prompt injection?\u201d on a security questionnaire",
    seoTitle: "Prompt injection on a security questionnaire",
    description:
      "The five-part answer a reviewer accepts: detection with rates, containment when it misses, least privilege, a verifiable audit trail, tests. With a template.",
    tag: "Prompt injection",
    keywords: [
      "security questionnaire prompt injection",
      "how do you prevent prompt injection",
      "AI security questionnaire answers",
      "prompt injection controls",
      "OWASP ASI01",
    ],
    published: "2026-11-22",
    readMinutes: 7,
    image: {
      src: "/product/injection-blocked.png",
      alt: "An AgentFox run where a retrieved document carried an instruction and the tool call it asked for was refused.",
      width: 1600,
      height: 900,
    },
    pillars: [
      { href: "/benchmark", label: "Benchmarks", why: "The numbers to quote, with their limits." },
      { href: "/docs/reference/owasp", label: "OWASP mapping", why: "Item by item, enforced or partial." },
      { href: "/docs/prove/audit", label: "Audit evidence", why: "The attachment that closes the question." },
    ],
  },
  {
    slug: "least-privilege-ai-agents-tool-permissions",
    title: "Least privilege for AI agents: how to scope tool permissions",
    seoTitle: "Least privilege for AI agents",
    description:
      "Grant per agent and per tool, draft grants from real traffic, limit arguments, set impact and provenance rules, require approval for the irreversible.",
    tag: "Audit and compliance",
    keywords: [
      "least privilege AI agents",
      "AI agent tool permissions",
      "agent permissions",
      "scope tool access for LLM agents",
      "capability grants",
    ],
    published: "2026-11-22",
    readMinutes: 8,
    image: {
      src: "/product/refusal.png",
      alt: "A refused tool call in AgentFox: the agent holds a grant for the tool, but the amount passed is above the limit on it.",
      width: 1600,
      height: 670,
    },
    pillars: [
      { href: "/docs/govern", label: "Tool access", why: "See, allow, limit, require approval." },
      { href: "/docs/concepts", label: "Core concepts", why: "Grants, impact and provenance defined." },
      { href: "/benchmark", label: "Benchmarks", why: "What the default grants cost in finished tasks." },
    ],
  },
  {
    slug: "mcp-server-security-checklist",
    title: "MCP server security checklist for enterprises",
    seoTitle: "MCP server security checklist",
    description:
      "Ten checks for every MCP server your agents load: inventory, pinned version, secrets, auth, a tool snapshot, descriptions read as code, grants, audit.",
    tag: "MCP security",
    keywords: [
      "MCP server security checklist",
      "MCP security",
      "Model Context Protocol security",
      "MCP tool poisoning",
      "enterprise MCP governance",
    ],
    published: "2026-11-22",
    readMinutes: 8,
    image: {
      src: "/blog/mcp-page.png",
      alt: "The MCP page in AgentFox: each server with its version, the tools it exposes and which agents may call them.",
      width: 3200,
      height: 1800,
    },
    pillars: [
      { href: "/docs/connect/mcp", label: "MCP servers", why: "Scan, pin, record and grant, step by step." },
      { href: "/docs/govern", label: "Tool access", why: "Per-tool grants and limits." },
      { href: "/docs/reference/owasp", label: "OWASP mapping", why: "Where ASI04 is covered and where it is not." },
    ],
  },
  {
    slug: "red-team-your-own-ai-agent",
    title: "How to red-team your own AI agent before your customer does",
    seoTitle: "Red-team your own AI agent",
    description:
      "Five steps: define a failure as a tool call that should not happen, run the attack library with tools faked, let attacks adapt, gate the build, keep probing.",
    tag: "Red teaming",
    keywords: [
      "red team AI agent",
      "how to red team an LLM agent",
      "AI agent penetration testing",
      "prompt injection testing",
      "agent security testing in CI",
    ],
    published: "2026-11-22",
    readMinutes: 7,
    image: {
      src: "/blog/playground-agents.png",
      alt: "The attack test in AgentFox: one row per attack set, with how many attacks got through before and after the basic guardrails.",
      width: 1600,
      height: 900,
    },
    pillars: [
      { href: "/docs/test", label: "Attack tests", why: "Run the library against your own agent." },
      { href: "/docs/test/ci", label: "CI and production", why: "Fail the build when it gets weaker." },
      { href: "/live", label: "Live", why: "Our own agent, attacked every hour." },
    ],
  },
  {
    slug: "lethal-trifecta-ai-agents",
    title: "The lethal trifecta is three safe tools in one agent",
    seoTitle: "Lethal trifecta: find it in your own agents",
    description:
      "Three tools that each pass review become an exfiltration path when one agent holds all of them. How to find the lethal trifecta in your own repo.",
    tag: "Prompt injection",
    keywords: [
      "lethal trifecta",
      "AI agent data exfiltration",
      "prompt injection exfiltration",
      "AI agent tool permissions",
      "agent security scan",
    ],
    published: "2026-11-19",
    readMinutes: 7,
    image: {
      src: "/blog/playground-agents.png",
      alt: "The AgentFox playground: five agents with the tools each one holds, including one that can move money up to a declared limit.",
      width: 1600,
      height: 900,
    },
    pillars: [
      { href: "/docs/concepts", label: "Concepts", why: "How a grant and argument provenance decide a call." },
      { href: "/playground", label: "Playground", why: "Try to talk an agent into a call it was never granted." },
    ],
  },
  {
    slug: "llm-guard-vs-agentfox-agentdojo",
    title: "LLM Guard vs AgentFox on AgentDojo: it finishes more tasks than we do",
    seoTitle: "LLM Guard vs AgentFox, measured on AgentDojo",
    description:
      "We ran LLM Guard and AgentFox containment on the same 588 AgentDojo attacks. It let 86 through, we let none, and it finishes more benign tasks than we do.",
    tag: "Benchmarks",
    keywords: [
      "LLM Guard vs AgentFox",
      "LLM Guard alternative",
      "prompt injection detector comparison",
      "AgentDojo benchmark",
      "open source LLM guardrails comparison",
    ],
    published: "2026-11-19",
    readMinutes: 8,
    image: {
      src: "/blog/benchmark-containment.png",
      alt: "The AgentFox benchmark page: containment results with the benign task column shown beside the attack column.",
      width: 1600,
      height: 900,
    },
    pillars: [
      { href: "/benchmark", label: "Benchmark", why: "Every arm in this post, with the result files behind it." },
      { href: "/docs/concepts", label: "Concepts", why: "What containment checks when it never reads the payload." },
    ],
  },
  {
    slug: "ai-agent-guardrail-latency",
    title: "How much latency does a guardrail add to an AI agent? We measured 109 agent repositories",
    seoTitle: "Guardrail latency, measured on 109 agents",
    description:
      "A guard check adds 57.4 ms at the median on traffic from 109 real agent repositories. What moves it, and how it compares with other guards.",
    tag: "Benchmarks",
    keywords: [
      "AI guardrail latency",
      "LLM guardrails latency",
      "prompt injection detection latency",
      "AI agent security performance",
      "LLM Guard vs NeMo Guardrails",
    ],
    published: "2026-10-28",
    readMinutes: 7,
    image: {
      src: "/blog/latency-benchmark.png",
      alt: "The AgentFox latency benchmark page: median latency per check with the ML classifier, per tool call, and without the model.",
      width: 1600,
      height: 900,
    },
    pillars: [
      { href: "/benchmark", label: "Benchmark", why: "AgentFox against other guards on the same machine." },
      { href: "/benchmark", label: "Security benchmarks", why: "What the checks catch, including the losses." },
      { href: "/docs/quickstart", label: "Quickstart", why: "From pip install to a governed agent." },
    ],
  },
  {
    slug: "agentfox-0-5-release",
    title: "AgentFox 0.5: one-command setup and multi-agent systems scanned as their agents",
    seoTitle: "AgentFox 0.5: agentfox up and multi-agent scans",
    description:
      "agentfox up takes a project to governed in one command, multi-agent repositories scan as separate agents, about seventy validators ship built in.",
    tag: "Release notes",
    keywords: [
      "AgentFox 0.5",
      "AI agent guardrails release",
      "multi-agent security",
      "AI agent setup",
      "Guardrails AI validators",
    ],
    published: "2026-10-17",
    readMinutes: 6,
    image: {
      src: "/blog/release-0-5.png",
      alt: "The AgentFox agent map for a payments agent after setup: its model, four tools, the rails where guardrails apply, and the attack test panel.",
      width: 1600,
      height: 900,
    },
    pillars: [
      { href: "/docs/quickstart", label: "Quickstart", why: "From pip install to a governed agent." },
      { href: "/docs/discover", label: "Scan a repo", why: "See every agent, tool and MCP server your code defines." },
      { href: "/pricing", label: "Editions", why: "What is open core and what is Enterprise." },
    ],
  },
  {
    slug: "ascii-smuggling-unicode-tag-prompt-injection",
    title: "ASCII smuggling: prompt injection you cannot see",
    description:
      "Unicode tag characters hide an instruction from every reviewer while a model still reads it. How ASCII smuggling works, and how to detect it precisely.",
    tag: "Prompt injection",
    keywords: [
      "ASCII smuggling",
      "Unicode tag characters prompt injection",
      "invisible prompt injection",
      "hidden prompt injection",
      "prompt injection detection",
    ],
    published: "2026-10-17",
    readMinutes: 7,
    image: {
      src: "/product/injection-observed.png",
      alt: "An AgentFox run whose retrieved document carries an instruction: allowed while the rule watches, and marked would block.",
      width: 1600,
      height: 900,
    },
    pillars: [
      { href: "/docs/reference/detectors", label: "Detector reference", why: "unicode.tags and every other detector, with surfaces." },
      { href: "/blog/prompt-injection-containment-not-detection", label: "Containment", why: "Why the guarantee comes from grants, not detection." },
      { href: "/playground", label: "Playground", why: "Try an injection against three agents, no account." },
    ],
  },
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
      alt: "The AgentFox docs page for MCP servers: scan the servers in a repository and on your machine, then pin each server's version.",
      width: 1600,
      height: 900,
    },
    pillars: [
      { href: "/docs/connect/mcp", label: "MCP servers guide", why: "Scan configs, pin tools, govern calls." },
      { href: "/live", label: "Live", why: "Our own agent, attacked hourly, results unedited." },
      { href: "/docs/limits", label: "Limits", why: "What AgentFox does not catch yet." },
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
      src: "/blog/containment-issue.png",
      alt: "An AgentFox issue: a payments.transfer above the agent's granted limit, blocked as outside the limits of its permission, with the reason in plain words.",
      width: 1600,
      height: 900,
    },
    pillars: [
      { href: "/benchmark", label: "Benchmarks", why: "The containment and AgentDojo results, losses included." },
      { href: "/docs/govern", label: "Contain tool calls", why: "Declarations, grants and provenance, with code." },
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
      alt: "The AgentFox docs page for Claude Code and Codex: the hooks that check shell commands, file edits and MCP calls before they run.",
      width: 1600,
      height: 900,
    },
    pillars: [
      { href: "/docs/connect/coding-agents", label: "Coding agents guide", why: "Install the hooks and the coding-agent pack." },
      { href: "/docs/concepts", label: "Concepts", why: "The same policy at the hook, gateway and SDK." },
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
      { href: "/docs/limits", label: "Limits", why: "What AgentFox does not catch yet." },
      { href: "/docs/test/ci", label: "Probe deployed agents", why: "Scheduled, opt-in attacks on your own agent." },
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
      alt: "An AgentFox run where a retrieved document carried an instruction: the tool result is blocked as injection in documents or tool results.",
      width: 1600,
      height: 900,
    },
    pillars: [
      { href: "/docs/reference/policies", label: "Policies", why: "Every rule and what it checks." },
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
      alt: "The AgentFox docs page for the audit trail: every allowed and blocked call recorded in a chain you can verify.",
      width: 1600,
      height: 900,
    },
    pillars: [
      { href: "/docs/prove/audit", label: "Prove it to an auditor", why: "The report, evidence packages, the verifier." },
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
