/**
 * /blog/feed.xml — RSS 2.0, from the same list as the index and the sitemap.
 *
 * Reachable without a session for the same reason /robots.txt is: middleware's
 * matcher skips any path with a file extension.
 */

import { AUTHOR, blogPath, postsByDate } from "@/lib/blog";
import { absolute, SITE_NAME } from "@/lib/site";

export const dynamic = "force-static";

const esc = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

export function GET(): Response {
  const posts = postsByDate();
  const items = posts
    .map((p) => {
      const url = absolute(blogPath(p.slug));
      return `    <item>
      <title>${esc(p.title)}</title>
      <link>${url}</link>
      <guid isPermaLink="true">${url}</guid>
      <pubDate>${new Date(`${p.published}T09:00:00Z`).toUTCString()}</pubDate>
      <category>${esc(p.tag)}</category>
      <author>noreply@useagentfox.com (${esc(AUTHOR.name)})</author>
      <description>${esc(p.description)}</description>
    </item>`;
    })
    .join("\n");
  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>${esc(SITE_NAME)} blog</title>
    <link>${absolute("/blog")}</link>
    <atom:link href="${absolute("/blog/feed.xml")}" rel="self" type="application/rss+xml" />
    <description>AI agent security, in depth: MCP, prompt injection, coding agents, red teaming and audit.</description>
    <language>en-gb</language>
    <lastBuildDate>${new Date(`${posts[0].published}T09:00:00Z`).toUTCString()}</lastBuildDate>
${items}
  </channel>
</rss>
`;
  return new Response(xml, { headers: { "Content-Type": "application/rss+xml; charset=utf-8" } });
}
