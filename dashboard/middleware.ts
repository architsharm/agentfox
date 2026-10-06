/**
 * The UX gate, not the security boundary — the gateway still 401s a missing, bad,
 * expired or revoked token on every request regardless of what happens here. This
 * just sends someone straight to /login instead of making them discover that from
 * an error on every page.
 *
 * Also stamps the request path onto a header so the root layout (a Server
 * Component) can tell it's rendering /login and skip the app chrome — Next.js has
 * no server-only "what page am I on" otherwise, short of a client component.
 */

import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE } from "@/lib/product/api";

// /playground is the public, unauthenticated demo (dashboard/app/(marketing)/playground) — it
// talks directly to the gateway's own unauthenticated `/api/playground/*` routes
// from the browser, never through this app's cookie-authenticated `api()` helper,
// so it needs no session here either.
//
// /benchmark is public for the same reason: it is the page the playground's
// "read the full benchmark" link points at, so it is read by people who have no
// account yet. It is a static page with no session and no API call.
//
// "/" and "/how-it-works" are public because the root URL is where an audience
// arriving from a link lands, and redirecting them to /login put a sign-in wall in
// front of a product with nothing anywhere saying what it is. "/" is not a page
// that is public *instead of* the app: app/page.tsx renders the landing page when
// there is no session cookie and the unchanged Overview when there is one, so a
// signed-in user sees no difference. The entry here only stops the redirect.
//
// Note the match below is `=== p` or `startsWith(p + "/")`, so the "/" entry matches
// the root path exactly and never the whole site: no path begins with "//".
// /product is public because components/marketing/nav.tsx links to it from the
// public header on "/" itself, under a comment promising that nav "links point only
// at pages a signed-out visitor can actually open". It was not in this list, so the
// first row of the nav on the landing page bounced the visitor to /login. Like
// /benchmark it is a static page with no session and no API call.
//
// /privacy, /terms, /security and /legal are public for a reason that is not really
// about SEO: a legal page behind a sign-in wall is worse than no legal page. A
// stranger deciding whether to paste something into the playground has to be able to
// read what happens to it *before* they have an account, and a visitor who wants to
// know what the hosted service promises must not have to accept it to find out. Like
// /product they are static pages with no session and no API call.
//
// The generated metadata routes are public because their whole purpose is to be
// fetched by a crawler or an unfurler, which has no session. /robots.txt and
// /sitemap.xml are already excluded by the extension rule in the matcher below;
// /opengraph-image, /twitter-image, /icon and /apple-icon have no extension, so
// without these entries Reddit, Slack, X and Discord would all be served a redirect
// to /login where they asked for a PNG, and the unfurl would stay blank.
/**
 * What needs a session, expressed as a prefix.
 *
 * This replaced a list. Every private route now lives under `/app` and every API
 * route except the auth handshake under `/api`, so the question "is this page
 * private" is two `startsWith` calls rather than a twenty-entry allow-list that
 * had to be kept in step with `app/layout.tsx`'s chromeless list and
 * `app/robots.ts`'s crawl list. The three drifted, and the way they drifted was
 * always the same: a new public page was added and one of the three was missed,
 * so a page meant for signed-out visitors redirected them to a sign-in form.
 *
 * The matcher below already excludes static files by extension. That is load
 * bearing: without it a signed-out visitor's request for a marketing screenshot
 * has no session cookie, gets redirected to /login, and the browser receives HTML
 * where it asked for an image — every picture on the public home page broken, and
 * only for the signed-out visitors the page exists for.
 */
const PRIVATE_PREFIXES = ["/app", "/api"];

/**
 * Where the private routes used to live, before they moved under `/app`.
 *
 * A bookmark to /agents or a link in somebody's runbook would 404 without this,
 * and a 404 is the worst of the options: the page exists, it is one segment away,
 * and the visitor has no way to know that. 308 rather than 302 because the move is
 * permanent and the method must be preserved — a 302 on a POST would turn a form
 * submission into a GET.
 *
 * This list is allowed to go stale in one direction only. A segment removed from
 * it stops redirecting, which is a dead link; a segment left in it that no longer
 * exists redirects to a 404 under /app, which is the same 404 the visitor would
 * have got anyway. Neither leaks anything, because /app is behind the session
 * check below either way.
 */
const MOVED_TO_APP = [
  "/start", "/agents", "/sources", "/findings", "/traces", "/evals",
  "/policies", "/entitlement", "/approvals", "/compliance", "/glossary",
  "/escalation", "/board", "/guardrails", "/settings",
];

/**
 * The exceptions under `/api`: routes that by definition run before there is a
 * session to check.
 *
 *   * `/api/auth` — the GitHub OAuth handshake, which is how a session comes to
 *     exist in the first place.
 *   * `/api/waitlist` — the pricing page's hosted-cloud signup form. Joining a
 *     waitlist is what someone does before they have an account, so a redirect to
 *     /login here does not protect anything: it discards the signup of the only
 *     kind of visitor the form exists for, and does it silently, because a plain
 *     form POST has no client JS to notice it landed on a login page.
 *
 * This stays a short list of exact route prefixes rather than becoming a pattern.
 * Everything else under `/api` proxies an authenticated gateway call, and the
 * failure mode of a too-broad rule here is the opposite of the one above: not a lost
 * signup, an unauthenticated request reaching a route that assumed it could not be.
 * The gateway is still the security boundary — it 401s a missing or bad token on
 * every route regardless — but the two public entries above are public *there* too,
 * which is what makes them safe to list here.
 */
const PUBLIC_API_PREFIXES = ["/api/auth", "/api/waitlist"];

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const headers = new Headers(req.headers);
  headers.set("x-pathname", pathname);

  // A page whose control-plane call came back 401/403 links here. The cookie is
  // still set and still looks fine to the check below, so without clearing it
  // the user is stuck in a loop: /login sees a cookie and bounces them back into
  // the app, which 401s again. This is the one place that can actually drop it —
  // a Server Component cannot set cookies. `expired=1` is what the login page
  // reads to explain what happened; the incoming value is never rendered.
  if (pathname === "/login" && req.nextUrl.searchParams.get("session") === "expired") {
    const url = new URL("/login", req.url);
    url.searchParams.set("expired", "1");
    const res = NextResponse.redirect(url);
    res.cookies.delete(SESSION_COOKIE);
    return res;
  }

  const underPrefix = (p: string) => pathname === p || pathname.startsWith(`${p}/`);

  const moved = MOVED_TO_APP.find(underPrefix);
  if (moved) {
    const url = new URL(`/app${pathname}${req.nextUrl.search}`, req.url);
    return NextResponse.redirect(url, 308);
  }

  const isPrivate =
    PRIVATE_PREFIXES.some(underPrefix) && !PUBLIC_API_PREFIXES.some(underPrefix);
  const signedIn = Boolean(req.cookies.get(SESSION_COOKIE)?.value);

  if (isPrivate && !signedIn) {
    const url = new URL("/login", req.url);
    return NextResponse.redirect(url);
  }
  return NextResponse.next({ request: { headers } });
}

// Static files under public/ are excluded by extension as well as by prefix. Without
// this, a signed-out visitor's request for a marketing screenshot is a request with no
// session cookie, so the redirect above sends it to /login and the browser gets HTML
// where it asked for an image: every picture on the public homepage renders broken,
// and only for the signed-out visitors the page exists for.
export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:webp|png|jpg|jpeg|gif|svg|ico|avif|woff2?|txt|xml|webmanifest|pdf)$).*)",
  ],
};
