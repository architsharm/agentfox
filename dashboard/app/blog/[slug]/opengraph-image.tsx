/**
 * Each post's social card: the post's own title on the site's card, so a
 * shared link reads as the article rather than as the homepage.
 */

import { articleOgImage, OG_CONTENT_TYPE, OG_SIZE } from "@/app/og";
import { getPost, SLUGS } from "@/lib/blog";

export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;
export const alt = "An article from the AgentFox blog.";

export function generateStaticParams() {
  return SLUGS.map((slug) => ({ slug }));
}

export default async function Image({ params }: { params: Promise<{ slug: string }> }) {
  const post = getPost((await params).slug);
  return articleOgImage({ kicker: post?.tag ?? "Blog", title: post?.title ?? "The AgentFox blog" });
}
