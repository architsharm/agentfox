/**
 * /sitemap.xml
 *
 * Only the URLs a signed-out visitor can actually open, which is exactly
 * middleware.ts's PUBLIC_PATHS minus the API prefix and the generated metadata
 * routes (an image is not a page). A sitemap that lists a URL
 * which answers with a redirect to /login is a crawl error reported back in Search
 * Console, so the authenticated app is absent rather than listed and disallowed.
 *
 * `changeFrequency` and `priority` are hints, not instructions, and they are set
 * from how these pages actually behave: the landing page and the product page
 * change when the product is described differently, the benchmarks change when a
 * benchmark is rerun, and the legal pages change when the service does.
 *
 * `lastModified` is the build time rather than a hardcoded date. Every one of these
 * pages is rendered from source in this repository, so a deployment is the only
 * thing that can change them, and stamping a date by hand is a date that goes stale
 * silently.
 */

import type { MetadataRoute } from "next";
import { BLOG_POSTS, blogPath } from "@/lib/blog";
import { DOC_PAGES } from "@/lib/docs";
import { ALL_PAGES } from "@/lib/nav";
import { SITE_URL } from "@/lib/site";

const BUILT_AT = new Date();

export default function sitemap(): MetadataRoute.Sitemap {
  // Derived from lib/nav.ts rather than kept here. This file used to hold its
  // own copy of the site's page list, which is how it came to be missing three
  // pages at once: the nav knew about them and nothing told the sitemap.
  //
  // A page without a `sitemap` hint is deliberately absent — /login is public
  // and crawlable so its own `noindex` can be read, and listing a noindex page
  // in a sitemap is a Search Console error for a page behaving as intended.
  const pages: MetadataRoute.Sitemap = ALL_PAGES.filter((page) => page.sitemap).map((page) => ({
    url: `${SITE_URL}${page.href}`,
    lastModified: BUILT_AT,
    changeFrequency: page.sitemap!.changeFrequency,
    priority: page.sitemap!.priority,
  }));
  // Every docs page, from lib/docs.ts (the docs sidebar's own list). /docs itself is
  // already in the site nav above.
  const listed = new Set(pages.map((p) => p.url));
  const docs: MetadataRoute.Sitemap = DOC_PAGES.map((page) => ({
    url: `${SITE_URL}${page.href}`,
    lastModified: BUILT_AT,
    changeFrequency: "monthly" as const,
    priority: 0.6,
  })).filter((page) => !listed.has(page.url));
  // Every blog post, from lib/blog.ts. A post's own date rather than the build
  // time: a post does not change because the site was redeployed, and a
  // lastModified that moves on every deploy teaches a crawler to ignore it.
  const posts: MetadataRoute.Sitemap = BLOG_POSTS.map((post) => ({
    url: `${SITE_URL}${blogPath(post.slug)}`,
    lastModified: new Date(`${post.updated ?? post.published}T00:00:00Z`),
    changeFrequency: "monthly" as const,
    priority: 0.7,
  }));
  return [...pages, ...docs, ...posts];
}
