import type { Metadata, Viewport } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import { Archivo } from "next/font/google";

import { SITE_NAME, SITE_URL, SITE_DESCRIPTION, HOME_TITLE, REPO_URL } from "@/lib/site";

/**
 * The display face.
 *
 * Until now `--mk-display` was aliased to Geist — the body font, and Vercel's
 * developer-tooling face. One family for everything is why this site read as a
 * repository with a stylesheet rather than as a product: there was no
 * typographic voice, only sizes.
 *
 * Archivo is a grotesk with an industrial cast and, unusually, a real width
 * axis, so headlines can sit slightly expanded without a second file. That is
 * the choice — sturdy and instrument-like, which is what the subject is —
 * and it is deliberately none of the faces this kind of page defaults to.
 *
 * Headings only. Geist keeps the body, where its shorter ascenders and plain
 * figures are better at small sizes and in tables.
 */
const archivo = Archivo({
  subsets: ["latin"],
  axes: ["wdth"],
  display: "swap",
  variable: "--font-archivo",
});
import "./globals.css";
import "./theme.css";
import "./marketing.css";

/**
 * Runs before paint so a stored theme choice never flashes the wrong colours.
 *
 * It only ever *departs* from light, which is rendered on <html> by the server.
 * Light being the default is the point: leaving the decision to the OS means a
 * visitor on a dark Mac meets a dark product on their first visit, having just come
 * from a marketing site that is designed light. "System" is still one of the three
 * choices in the sidebar; it is simply no longer the one nobody picked.
 *
 * The `catch` matters and is deliberately empty: localStorage throws outright in
 * some privacy modes, and the right outcome there is the light default already in
 * the markup.
 */
const THEME_INIT_SCRIPT = `(function(){try{var r=document.documentElement,t=localStorage.getItem("agentfox-theme");if(t==="system")r.removeAttribute("data-theme");else if(t==="dark")r.setAttribute("data-theme","dark");}catch(e){}})();`;

/**
 * Root metadata. Everything here is inherited by every route, so it holds only
 * what is true of the whole site; anything page-specific lives on the page.
 *
 * `metadataBase` is what turns the relative `canonical` and image paths below and
 * on every page into the absolute URLs a crawler and an unfurler need. It reads
 * the host from the environment (lib/site.ts) so a preview deployment does not
 * publish canonicals pointing at production.
 *
 * `title.template` means a page exports just its own name ("Glossary") and gets
 * "Glossary | AgentFox" in the tab and the unfurl. `title.default` is what a route
 * with no title of its own inherits.
 *
 * No `verification`, no `category`, and no keyword list beyond the six terms this
 * product is genuinely described by, because a longer list is not a ranking signal
 * and reads as stuffing to a human who views source.
 */
/**
 * Tints the browser chrome on mobile to the page's own ground, so the status bar
 * stops sitting in a different colour from the app underneath it. Two entries
 * rather than one: a single value would be wrong in whichever theme it is not.
 *
 * These are `--bg` in each theme, by hand. A media-query meta tag cannot read a
 * custom property, so if the ramp in globals.css moves, these move with it.
 */
export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fbfbfd" },
    { media: "(prefers-color-scheme: dark)", color: "#000000" },
  ],
};

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: HOME_TITLE,
    template: "%s | AgentFox",
  },
  description: SITE_DESCRIPTION,
  applicationName: SITE_NAME,
  keywords: [
    "AI agent governance",
    "AI agent security",
    "prompt injection",
    "tool call authorisation",
    "LLM guardrails",
    "agent audit trail",
  ],
  authors: [{ name: "AgentFox", url: REPO_URL }],
  // No `images` key in either block. app/opengraph-image.tsx and
  // app/twitter-image.tsx sit at the root of app/, and the file convention applies
  // them to every route beneath automatically, with a content hash in the URL that
  // busts a social network's image cache when the card changes. Listing an image
  // here as well is how a page ends up emitting two `og:image` tags pointing at
  // two different URLs for the same picture and letting the unfurler choose.
  openGraph: {
    type: "website",
    siteName: SITE_NAME,
    url: "/",
    title: HOME_TITLE,
    description: SITE_DESCRIPTION,
    locale: "en_GB",
  },
  twitter: {
    card: "summary_large_image",
    title: HOME_TITLE,
    description: SITE_DESCRIPTION,
  },
  robots: {
    index: true,
    follow: true,
    googleBot: { index: true, follow: true, "max-image-preview": "large", "max-snippet": -1 },
  },
  alternates: { canonical: "/" },
};

/**
 * Plain, predictable category nouns rather than a rhetorical-question framing
 * ("What is it" / "Does it work") — a newcomer scanning the sidebar once should
 * be able to guess which group a page lives in before clicking it.
 *
 * Grouping and labels follow the four-stage lifecycle (Discover / Monitor /
 * Test / Govern) that recurs across the AI-agent-governance and AI-security
 * category researched for this pass — Noma, Pillar Security, HiddenLayer,
 * SplxAI, Lasso, and Cisco AI Defense all converge on some version of
 * discover-what-exists -> test/validate -> runtime-protect -> govern. Two
 * splits from the previous grouping follow that research directly:
 *
 * - "Discover" (Agents, Sources) is pulled out on its own because "Discover"
 *   is the single most consistently-used word across that whole category for
 *   exactly this — an inventory of what exists (agents, MCP servers, data
 *   sources) — not an AgentFox-specific choice.
 * - "Monitor" keeps Findings and Traces, since those are the ongoing-activity
 *   record rather than the inventory itself, and "Monitor" was never actually
 *   flagged as unclear by the research — only "Quality" and the standalone
 *   "Reporting" group of one were.
 *
 * Compliance sits in Govern, not its own "Reporting" group of one — every
 * comparable governance product treats framework/control mapping as part of
 * governance, not a separate top-level stage, and a group with a single row
 * was just an extra click for no organizing benefit.
 *
 * Guardrail tuning and Escalation are NOT rows. They are tabs on Policies and on
 * Approvals, and they were also listed here as indented children of those two
 * rows — the same destination in the sidebar twice, drawn in a weaker style the
 * second time. A sidebar row and a tab on the page it opens are two controls for
 * one thing, and the reader has to work out that they agree. They are in
 * NAV_SEARCH_ONLY below instead, so typing the name still finds them.
 */
export default async function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    /* `data-theme="light"` is rendered here, on the server, and not only written by
       the script below. It is the default, so rendering it is what makes the markup
       React hydrates against match the DOM the script produced for the visitor who
       has chosen nothing — which is almost everybody. Stamping it from the script
       alone put an attribute on <html> that the server HTML did not have, and React
       reported a hydration mismatch on every first load.

       `suppressHydrationWarning` covers the remaining two cases, where the script
       legitimately disagrees with the server: a visitor who picked Dark, and one who
       picked System. It applies to this element's own attributes only, not to its
       subtree, so nothing else on the page stops being checked. */
    <html
      lang="en-GB"
      data-theme="light"
      suppressHydrationWarning
      className={`${GeistMono.variable} ${GeistSans.variable} ${archivo.variable}`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      {/* Nothing but the document.
       
          This layout used to decide, from an `x-pathname` header, whether to wrap
          its children in the app shell or in a bare div — and it is shared by the
          marketing site and the app, so Next never re-rendered it when a visitor
          navigated between the two. Clicking "Dashboard" on the home page landed
          on /app with the marketing wrapper still in place and no sidebar; a
          reload fixed it, because a reload renders the layout again.

          The shell moved to app/(product)/app/layout.tsx, which the router mounts only for
          the routes it belongs to. The wrapper that used to sit here was
          `.login-main { display: block; width: 100% }` — a div that did nothing —
          and every public page renders its own <main>, so it is simply gone. */}
      <body>{children}</body>
    </html>
  );
}
