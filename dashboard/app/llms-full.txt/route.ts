/**
 * /llms-full.txt: every public page's text in one file, for an assistant that
 * fetches one URL and answers from it (llmstxt.org's optional companion to
 * /llms.txt). The page list is the sitemap's, so a page cannot be here and gone
 * from the site. Each page is fetched from this deployment and cached for a day;
 * the route itself is dynamic so a build never has to reach the live site.
 */

import { BLOG_POSTS, blogPath } from "@/lib/marketing/blog";
import { DOC_PAGES } from "@/lib/docs/pages";
import { htmlToText } from "@/lib/marketing/llms-full";
import { ALL_PAGES } from "@/lib/marketing/nav";
import { SITE_DESCRIPTION, SITE_NAME, SITE_URL } from "@/lib/site";

export const dynamic = "force-dynamic";

const PATHS = [
  ...ALL_PAGES.filter((p) => p.sitemap).map((p) => p.href),
  ...DOC_PAGES.map((p) => p.href),
  ...BLOG_POSTS.map((p) => blogPath(p.slug)),
];

export async function GET(): Promise<Response> {
  const pages = await Promise.all(
    [...new Set(PATHS)].map(async (path) => {
      const url = `${SITE_URL}${path}`;
      try {
        const res = await fetch(url, { next: { revalidate: 86400 }, headers: { accept: "text/html" } });
        if (!res.ok) return null;
        return `## ${url}\n\n${htmlToText(await res.text())}`;
      } catch {
        return null;
      }
    }),
  );
  const body = [`# ${SITE_NAME}`, "", `> ${SITE_DESCRIPTION}`, "", `The index with one line per page is ${SITE_URL}/llms.txt.`, "", ...pages.filter(Boolean)].join("\n\n");
  return new Response(body, { headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "public, max-age=3600" } });
}
