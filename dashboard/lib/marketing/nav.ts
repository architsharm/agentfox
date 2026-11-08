/**
 * The site's pages, in one place. The header, the footer, `sitemap.ts` and
 * `llms.txt` all read this file, so a page cannot be in one and missing from
 * another.
 */

export type NavItem = {
  label: string;
  href: string;
  /** One line, published in llms.txt. */
  note: string;
  /** Sitemap hints. Omitted for anything that should not be indexed. */
  sitemap?: { changeFrequency: "weekly" | "monthly" | "yearly"; priority: number };
};

export type FooterColumn = { heading: string; items: NavItem[] };

const BENCHMARK: NavItem = {
  label: "Benchmark",
  href: "/benchmark",
  note: "Security benchmarks: containment with every detector off, an AgentDojo replay with its utility cost, detection rates against other guards, and an adaptive attack, each with its limits.",
  sitemap: { changeFrequency: "monthly", priority: 0.8 },
};
const LATENCY: NavItem = {
  label: "Latency benchmark",
  href: "/benchmark/latency",
  note: "What a guard check adds to an agent, measured on traffic from 109 real agent repositories, and against other guards on the same machine.",
  sitemap: { changeFrequency: "monthly", priority: 0.7 },
};
const PLAYGROUND: NavItem = {
  label: "Playground",
  href: "/playground",
  note: "Send attacks to a running agent in the browser. No account.",
  sitemap: { changeFrequency: "monthly", priority: 0.8 },
};
const LIVE: NavItem = {
  label: "Live",
  href: "/live",
  note: "Our own demo agent, attacked every hour through the real enforcement path. Results unedited, including what got through.",
  sitemap: { changeFrequency: "weekly", priority: 0.7 },
};
const PRICING: NavItem = {
  label: "Pricing",
  href: "/pricing",
  note: "Free to self-host under Apache-2.0. The hosted preview is free.",
  sitemap: { changeFrequency: "monthly", priority: 0.7 },
};
const BLOG: NavItem = {
  label: "Blog",
  href: "/blog",
  note: "How attacks on agents work, and the benchmarks behind each post.",
  sitemap: { changeFrequency: "weekly", priority: 0.7 },
};
const DOCS: NavItem = {
  label: "Docs",
  href: "/docs",
  note: "Install AgentFox, connect your agents, and the full reference.",
  sitemap: { changeFrequency: "weekly", priority: 0.8 },
};
const SECURITY: NavItem = {
  label: "Security",
  href: "/security",
  note: "How to report a vulnerability, and what has and hasn't been audited.",
  sitemap: { changeFrequency: "yearly", priority: 0.4 },
};
const SUPPORT: NavItem = {
  label: "Support",
  href: "/support",
  note: "Where to ask a question or report a bug.",
  sitemap: { changeFrequency: "monthly", priority: 0.5 },
};
const PRIVACY: NavItem = {
  label: "Privacy",
  href: "/privacy",
  note: "What the hosted service stores.",
  sitemap: { changeFrequency: "yearly", priority: 0.3 },
};
const TERMS: NavItem = {
  label: "Terms",
  href: "/terms",
  note: "Terms for the hosted service.",
  sitemap: { changeFrequency: "yearly", priority: 0.3 },
};

/** The landing page, which belongs in the sitemap and in no menu. */
export const HOME: NavItem = {
  label: "AgentFox",
  href: "/",
  note: "Guardrails for AI agents that stop attacks without blocking real customers.",
  sitemap: { changeFrequency: "weekly", priority: 1 },
};

/** Header links, kept to one. Everything else is linked from the pages and the footer. */
export const HEADER: NavItem[] = [BENCHMARK];
export const HEADER_CTA: NavItem = DOCS;

export const FOOTER: FooterColumn[] = [
  { heading: "Product", items: [PLAYGROUND, LIVE, PRICING] },
  { heading: "Benchmarks", items: [BENCHMARK, LATENCY] },
  { heading: "Resources", items: [DOCS, BLOG, SUPPORT] },
  { heading: "Company", items: [SECURITY, PRIVACY, TERMS] },
];

/** Every page, in one list. */
export const ALL_PAGES: NavItem[] = [HOME, BENCHMARK, LATENCY, PLAYGROUND, LIVE, PRICING, BLOG, DOCS, SECURITY, SUPPORT, PRIVACY, TERMS];

export const ALL_PATHS: string[] = ALL_PAGES.map((p) => p.href);
