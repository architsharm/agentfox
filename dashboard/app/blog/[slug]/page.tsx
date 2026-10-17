/**
 * /blog/<slug> — one post.
 *
 * Statically generated from lib/marketing/blog.ts. A slug that is not registered is a 404
 * rather than an empty shell, because `dynamicParams` is off.
 */

import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { BlogArticle } from "@/components/marketing/blog/article";
import { POST_BODIES } from "@/components/marketing/blog/posts";
import { AUTHOR, blogPath, getPost, SLUGS } from "@/lib/marketing/blog";
import { publicPageMetadata } from "@/lib/site";

export const dynamicParams = false;

export function generateStaticParams() {
  return SLUGS.map((slug) => ({ slug }));
}

type Params = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const post = getPost((await params).slug);
  if (!post) return {};
  const base = publicPageMetadata({
    title: post.seoTitle ?? post.title,
    description: post.description,
    path: blogPath(post.slug),
  });
  return {
    ...base,
    keywords: post.keywords,
    authors: [{ name: AUTHOR.name, url: AUTHOR.url }],
    // An article, not a website: this is what lets an unfurler show the date
    // and a search engine treat the page as dated content.
    openGraph: {
      ...base.openGraph,
      type: "article",
      publishedTime: post.published,
      modifiedTime: post.updated ?? post.published,
      section: post.tag,
      tags: post.keywords,
    },
  };
}

export default async function Page({ params }: Params) {
  const post = getPost((await params).slug);
  if (!post) notFound();
  const { Body, toc, faq } = POST_BODIES[post.slug];
  return (
    <BlogArticle post={post} toc={toc} faq={faq}>
      <Body />
    </BlogArticle>
  );
}
