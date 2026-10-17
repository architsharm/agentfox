/**
 * /robots.txt
 *
 * Every route that requires a session redirects a cookie-less request to /login,
 * so a crawler that follows one gets the sign-in page back under an app URL.
 * Letting that happen puts a wall of near-identical /login bodies in the index
 * under a dozen different URLs, which is worse for the site than those pages
 * simply not being there.
 *
 * This used to be a hand-maintained list of fifteen top-level segments — a third
 * copy of "what is private", alongside middleware.ts and layout.tsx, with no test
 * covering it. A route added to the app and forgotten here became crawlable, and
 * nothing failed. Now that every private route lives under /app it is one prefix,
 * and it cannot go stale: a new private page is under /app by construction, and a
 * page that is not under /app is not private.
 *
 * Serving /robots.txt at all needs it to be publicly reachable. It is: the
 * middleware matcher excludes anything ending in `.txt`.
 */

import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        // No trailing slash. `Disallow` is a prefix match, so "/app" covers /app
        // itself and everything under it, whereas "/app/" would have left the
        // dashboard's own index page crawlable.
        disallow: [
          "/app",
          // The route handlers under app/api. Nothing here is a document, and the
          // OAuth callback in particular should never be fetched by a crawler.
          "/api/",
        ],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
