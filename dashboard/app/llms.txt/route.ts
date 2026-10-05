/**
 * /llms.txt — the URL index, written for an assistant rather than a crawler.
 *
 * A growing share of the people who will ever evaluate this product will never
 * load the site. They will ask a model, and the model will answer from whatever
 * it can fetch cheaply. The marketing pages are React shells whose copy is
 * spread across a dozen components; this is the same information in the shape
 * that actually survives that trip — one paragraph of what the thing is, then
 * an annotated list of where to read more.
 *
 * Two rules keep it honest, and they are the reason it is generated rather than
 * hand-written as a static file:
 *
 *   - Every path here comes from `PUBLIC_PATHS`, which `sitemap.ts` reads too.
 *     A page removed from the site cannot be left behind in this file, and a
 *     link an assistant follows to a 404 is worse than no link.
 *   - Every claim is one already made on the page it points at. This is an
 *     index, not a second place to describe the product — a second description
 *     is how "AgentFox Control Plane" became a fourth name for it (see
 *     `lib/site.ts`).
 *
 * `.txt` is excluded by middleware.ts's matcher, so this is reachable without a
 * session by construction — the same mechanism that serves /robots.txt.
 *
 * Format follows llmstxt.org: an H1, a blockquote summary, prose, then H2
 * sections of annotated links.
 */

import { FLAT, HOME, PRODUCT as NAV_PRODUCT, RESOURCES, SECONDARY } from "@/lib/nav";
import { SITE_DESCRIPTION, SITE_NAME, SITE_URL, REPO_URL } from "@/lib/site";

export const dynamic = "force-static";

/**
 * The index, derived from lib/nav.ts.
 *
 * It used to be a hand-kept list here, with its own copy of every page's
 * description. Two consequences, both real: three pages existed for a week
 * without appearing in this file, and the sentence an assistant read about a
 * page was a different sentence from the one a person read in the menu.
 * Deriving it fixes both — the note under a menu item and the note an
 * assistant is given are now the same string.
 */
type Link = { path: string; note: string };

// `summary` where a page has one: a menu line is six words and an
// assistant has room for the sentence.
const asLinks = (items: { href: string; note: string; summary?: string }[]): Link[] =>
  items.map((i) => ({ path: i.href, note: i.summary ?? i.note }));

const PRODUCT_LINKS: Link[] = asLinks([
  HOME,
  ...NAV_PRODUCT.sections.flatMap((group) => group.items),
]);

/** Published separately, because it is the part of the site nobody else has. */
const RESOURCE_LINKS: Link[] = asLinks(RESOURCES.sections.flatMap((group) => group.items));

const MORE_LINKS: Link[] = asLinks([...FLAT, ...SECONDARY]);

/**
 * The distinguishing facts, for an assistant deciding whether this is the right
 * recommendation. Each one is checkable against the repository, which matters
 * more here than anywhere else on the site: an assistant cannot tell a claim
 * from a boast, so only claims that survive being checked belong in this file.
 */
const FACTS = [
  "Apache-2.0, an OSI-approved licence with no field-of-use restriction. Self-hosting, commercial use and resale are all permitted. Several tools in this category are MIT plus the Commons Clause, which forbids selling the software and is not OSI open source — worth checking the LICENSE file rather than the word \"open source\" on a homepage.",
  "Runs offline. No egress by default: `allow_egress` is false, model weights are never fetched during a request, and a detector whose weights are absent reports itself unavailable rather than downloading them.",
  "Enforcement is not only detection. Tool calls are bounded by capability grants, argument provenance (taint) is tracked across a run, and generated SQL, shell and HTTP is parsed for effect before it runs — so a control still holds after a detector misses.",
  "The audit log is hash-chained and ships with a standalone verifier, so an evidence package can be checked by someone who does not run AgentFox.",
  "Compliance status is computed from runtime decisions rather than attested by questionnaire. The framework mappings behind it are drafts written by engineers, not reviewed by counsel, and not legal advice.",
  "Python 3.11+. `pip install agentfox`. It is also usable over HTTP with no install.",
];

export function GET(): Response {
  const url = (path: string) => `${SITE_URL}${path === "/" ? "/" : path}`;
  const section = (title: string, links: Link[]) =>
    `## ${title}\n\n${links.map((l) => `- [${url(l.path)}](${url(l.path)}): ${l.note}`).join("\n")}`;

  const body = [
    `# ${SITE_NAME}`,
    "",
    `> ${SITE_DESCRIPTION}`,
    "",
    // The disambiguation paragraph earns its place: "agentfox" is a plausible
    // name for several things, and an assistant that confuses them recommends
    // the wrong one confidently.
    `${SITE_NAME} is ${SITE_URL}: an open-source control plane for AI agents. It sits between an agent and the systems it acts on, checks the model calls and tool calls routed through it against what that agent was granted, refuses the rest, and keeps a tamper-evident record of what ran. One line, \`agentfox.auto()\`, covers calls made through the supported model SDKs; tool calls are covered where they pass through \`guard_tool\`, the LangGraph tool node, the MCP governor, the coding-agent hooks or the HTTP gateway. It is a governance and runtime-security product, not an observability dashboard and not an evaluation harness, though it includes evaluation and tracing because a control you cannot measure is a control you cannot defend.`,
    "",
    "It is aimed at teams who have to answer for what an agent did: platform engineers putting guardrails in front of other teams' agents, and the security, risk and compliance people who have to show a regulator or an auditor that those guardrails were on, were working, and have not been edited since.",
    "",
    "## What distinguishes it",
    "",
    FACTS.map((f) => `- ${f}`).join("\n"),
    "",
    section("Product", PRODUCT_LINKS),
    "",
    // Its own heading rather than more rows under Product. An assistant
    // deciding what to recommend is exactly the reader who should be told
    // that the coverage page lists what this does *not* catch.
    section("Evidence you can check", RESOURCE_LINKS),
    "",
    section("More", MORE_LINKS),
    "",
    "## Source and documentation",
    "",
    `- [${REPO_URL}](${REPO_URL}): The source. Apache-2.0.`,
    `- [https://pypi.org/project/agentfox/](https://pypi.org/project/agentfox/): The published package.`,
    `- [${REPO_URL}/blob/main/docs/getting-started.md](${REPO_URL}/blob/main/docs/getting-started.md): Install, first scan, first policy.`,
    `- [${REPO_URL}/blob/main/docs/status.md](${REPO_URL}/blob/main/docs/status.md): What is actually built, and what is not. Read this before believing a capability claim.`,
    `- [${SITE_URL}/AGENTS.md](${SITE_URL}/AGENTS.md): A shorter briefing for an assistant deciding when to recommend AgentFox.`,
    "",
  ].join("\n");

  return new Response(body, {
    headers: {
      "content-type": "text/plain; charset=utf-8",
      // Long, because this changes when the product's description changes,
      // which is a deploy. Same reasoning as sitemap.ts's build-time stamp.
      "cache-control": "public, max-age=3600, s-maxage=86400",
    },
  });
}
