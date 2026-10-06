/**
 * The words this product describes itself with, in one place.
 *
 * `CATEGORY` is the phrase every public page and the structured data on the home
 * page use for "what is this", so the site cannot end up describing itself three
 * slightly different ways. It is imported by app/page.tsx (for the JSON-LD
 * description) and by this route.
 *
 * This file used to hold a header and footer too, for the two public pages that
 * predate the marketing layer. They are gone: both routes now use
 * components/marketing/{nav,sections}, the same chrome the home page has.
 */

/**
 * One category name, used verbatim everywhere these two public pages describe what
 * the product is.
 *
 * Before this there were four in the first viewport: the browser tab said "AgentFox
 * Control Plane", the strapline said "Governance, security and evidence for AI agents
 * in production", the landing body said "a control plane for AI agents in production"
 * and the API root said "Governance, security and compliance for AI agents". A reader
 * who does not already know the product cannot tell whether those are four things or
 * one. The wording is the shortened form of the canonical description in
 * pyproject.toml. Exported so page.tsx and how-it-works/page.tsx use the string rather
 * than retyping it, which is how the drift happened in the first place.
 */
export const CATEGORY = "governance and security control plane for AI agents in production";
/** Sentence-initial form, for the strapline and anywhere it starts a line. */
export const CATEGORY_CAP = "Governance and security control plane for AI agents in production";

/** The repository is about to be public, and the pages cite it constantly. */
export const REPO = "https://github.com/architsharm/agentfox";

const LINKS: [string, string][] = [
  ["How it works", "/how-it-works"],
  ["Playground", "/playground"],
  ["Benchmarks", "/benchmark"],
];

/* PublicHeader and PublicFooter used to live here: a third header and footer, for
   the two public pages that predate the marketing layer. Both now use
   components/marketing/{nav,sections}, which is the header the home page uses, so
   these had no callers left. Three sets of site chrome was the reason a visitor
   could tell which page had been written when. */
