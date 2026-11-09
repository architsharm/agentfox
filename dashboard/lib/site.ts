/**
 * The handful of absolute facts every metadata route needs, in one place.
 *
 * `metadataBase`, `robots.ts` and `sitemap.ts` all have to emit absolute URLs, and
 * a preview deployment that hardcodes the production host emits canonicals pointing
 * at a page that is not the one being previewed. So the host is an environment
 * variable with production as the fallback.
 *
 * Deliberately NOT a `NEXT_PUBLIC_*` variable and deliberately not in
 * next.config.mjs's `env` block, for the reason that file already states: a
 * `NEXT_PUBLIC_*` value is inlined into the bundle at build time, so one built
 * container could never be repointed at another host without a rebuild. Every
 * consumer of this module runs on the server, so a plain server variable read at
 * request time is both sufficient and repointable.
 */
import { env } from "@/lib/env";

/** Production host. The custom domain, replacing guardrails-agentfox.vercel.app. */
const FALLBACK_SITE_URL = "https://useagentfox.com";

/** No trailing slash, so `new URL(path, SITE_URL)` and template literals agree. */
export const SITE_URL = (env("SITE_URL") || FALLBACK_SITE_URL).replace(/\/+$/, "");

export const SITE_NAME = "AgentFox";

/**
 * The one-line description of the whole product, used by the root metadata in
 * app/layout.tsx and by "/" itself. Shared so the site default and the homepage
 * cannot say two different things, which is how "AgentFox Control Plane" became a
 * fourth name for the product alongside the strapline and the body copy.
 *
 * 56 and 140 characters: a title is truncated by Google at roughly 60 and a
 * description at roughly 160, and a sentence that is cut mid-clause reads as
 * carelessness in the one place a stranger is deciding whether to click.
 */
export const HOME_TITLE = "AgentFox: AI agent governance and security control plane";
export const HOME_DESCRIPTION =
  "One control plane for AI agent security: discovery, access control, runtime guardrails, and an audit trail.";

/** The site-wide default, for routes that do not describe themselves. */
export const SITE_DESCRIPTION =
  "Open source control plane for AI agents: discover what is running, least privilege on tool calls, and an audit trail you can check without us.";

/**
 * The repository. Also spelled out in components/marketing/nav.tsx, which is a
 * rendered link where this is structured
 * data, and they are all the same string. Verified against LICENSE at the repo
 * root, which is the Apache License 2.0.
 */
export const REPO_URL = "https://github.com/architsharm/agentfox";

/** Verified in components/marketing/editions.tsx and components/marketing/Playground.tsx. */
export const SUPPORT_EMAIL = "support@nometria.com";

/** Alt text for the site-wide social card (app/og.tsx draws it). */
export const SOCIAL_IMAGE_ALT =
  "AgentFox: your agent believes what it reads, so limit what it is allowed to do. Open source, Apache-2.0.";

/** The card's size and alt text, for the `images` entries in publicPageMetadata. */
const SOCIAL_IMAGE = { width: 1200, height: 630, alt: SOCIAL_IMAGE_ALT, type: "image/png" };

/** Absolute URL for a path, for canonicals and structured data. */
export function absolute(path: string): string {
  return `${SITE_URL}${path === "/" ? "/" : path}`;
}

/**
 * Metadata for one public page.
 *
 * The reason this is a helper rather than six hand-written objects: Next merges
 * metadata shallowly, so a page that exports only `title` and `description`
 * inherits the ROOT's `openGraph` block wholesale, title included. Every public
 * page would then unfurl in Slack and on Reddit as the homepage. Each page has to
 * restate its own title and description inside `openGraph` and `twitter`, and
 * doing that by hand six times is six chances for the three copies to disagree.
 *
 * The card is named here explicitly. app/opengraph-image.tsx and
 * app/twitter-image.tsx at the root of app/ only reach a route that says nothing
 * about `openGraph`: a page that sets its own `openGraph` block (which every page
 * using this helper does, for the reason above) replaces the inherited one, image
 * included. Without `images` here every public page except "/" unfurled with no
 * picture at all. An explicit entry also beats an image file in the page's own
 * segment, so a route that has one ("/" and the blog posts) passes `ownImage` and
 * keeps its file, with the content hash that busts an unfurler's cache.
 */
export function publicPageMetadata(opts: {
  title: string;
  description: string;
  path: string;
  /** True for a page that should be crawled but not indexed, i.e. /login. */
  noIndex?: boolean;
  /** The route has its own opengraph-image/twitter-image file in its segment. */
  ownImage?: boolean;
}) {
  const { title, description, path, noIndex, ownImage } = opts;
  return {
    title,
    description,
    alternates: { canonical: path },
    openGraph: {
      type: "website" as const,
      siteName: SITE_NAME,
      url: path,
      title,
      description,
      locale: "en_GB",
      ...(ownImage ? {} : { images: [{ url: "/opengraph-image", ...SOCIAL_IMAGE }] }),
    },
    twitter: {
      card: "summary_large_image" as const,
      title,
      description,
      ...(ownImage ? {} : { images: [{ url: "/twitter-image", ...SOCIAL_IMAGE }] }),
    },
    ...(noIndex ? { robots: { index: false, follow: true } } : {}),
  };
}

/**
 * Metadata for a page that lives behind the sign-in wall.
 *
 * `index: false` is belt to the braces of two other things: middleware.ts already
 * answers an unauthenticated request for these routes with a redirect to /login,
 * and app/robots.ts already disallows them. A crawler should therefore never
 * reach the HTML this tag is in. It is here for the case where one of those two
 * is later relaxed by someone who is not thinking about search, because the
 * failure mode is a dozen URLs in the index all showing the same sign-in form.
 *
 * `follow` stays true: there is nothing secret about the link graph, and a
 * nofollow here would also apply to the public links in the page footer.
 *
 * The `title` is not wasted effort even though no crawler sees it. A signed-in
 * user with nine tabs open currently gets nine tabs reading "AgentFox Control
 * Plane", and the tab title is the only thing that tells them apart.
 */
export function appPageMetadata(title: string, description?: string) {
  return {
    title,
    ...(description ? { description } : {}),
    robots: { index: false, follow: true },
    // Explicitly null, not omitted. Next merges metadata from the root layout
    // down, so a page that says nothing about `alternates` inherits the root's
    // `canonical: "/"` and every screen in the app then declares itself to be a
    // duplicate of the homepage. `null` emits no canonical link at all, which is
    // the right answer for a page that is not a search result in the first place.
    alternates: { canonical: null },
  };
}
