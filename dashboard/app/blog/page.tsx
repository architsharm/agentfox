/**
 * /blog — every post, newest first.
 *
 * The posts are the long-form argument for pages that already exist: each one
 * ends in the product page, docs guide and benchmark it is evidence for. The
 * index says so in its own lede, so nobody mistakes it for a news feed.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { PostCard } from "@/components/blog/card";
import { MarketingNav } from "@/components/marketing/nav";
import { CTA, Footer } from "@/components/marketing/sections";
import { BLOG_POSTS, blogPath, postsByDate } from "@/lib/blog";
import { absolute, publicPageMetadata, SITE_NAME } from "@/lib/site";

const TITLE = "AI agent security blog";
const DESCRIPTION =
  "Long-form writing on AI agent security: MCP tool poisoning, prompt injection, Claude Code hooks, red teaming and audit trails, with the numbers behind each.";

export const metadata: Metadata = {
  ...publicPageMetadata({ title: TITLE, description: DESCRIPTION, path: "/blog" }),
  alternates: {
    canonical: "/blog",
    types: { "application/rss+xml": [{ url: "/blog/feed.xml", title: `${SITE_NAME} blog` }] },
  },
};

export default function Page() {
  const [featured, ...rest] = postsByDate();
  const tags = Array.from(new Set(BLOG_POSTS.map((p) => p.tag)));
  return (
    <div className="mk">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify({
            "@context": "https://schema.org",
            "@type": "Blog",
            name: `${SITE_NAME} blog`,
            description: DESCRIPTION,
            url: absolute("/blog"),
            blogPost: BLOG_POSTS.map((p) => ({
              "@type": "BlogPosting",
              headline: p.title,
              url: absolute(blogPath(p.slug)),
              datePublished: p.published,
            })),
          }).replace(/</g, "\\u003c"),
        }}
      />
      <MarketingNav />
      <main>
        <section className="mk-section-tight blog-hero mk-ink-act">
          <div className="mk-hero-glow" aria-hidden />
          <div className="mk-wrap" style={{ position: "relative" }}>
            <p className="mk-kicker mk-up mk-d1">Blog</p>
            <h1 className="mk-h1 mk-up mk-d2" style={{ marginTop: 14 }}>
              Securing AI agents, <em>in depth</em>
            </h1>
            <p className="mk-lede mk-up mk-d3" style={{ marginTop: 20, maxWidth: 720 }}>
              How the attacks on agents actually work, what stops them, and what does not. Every
              number links to the <Link href="/benchmark">benchmark</Link> it came from, losses
              included.
            </p>
            <p className="blog-tags mk-up mk-d4">
              {tags.map((t) => (
                <span key={t} className="mk-chip">
                  {t}
                </span>
              ))}
            </p>
          </div>
        </section>

        <section className="mk-section-tight">
          <div className="mk-wrap">
            <PostCard post={featured} featured />
            <div className="blog-grid" style={{ marginTop: 28 }}>
              {rest.map((p) => (
                <PostCard key={p.slug} post={p} />
              ))}
            </div>
            <p className="mk-fine" style={{ marginTop: 32 }}>
              Subscribe with the <a href="/blog/feed.xml">RSS feed</a>, or{" "}
              <Link href="/live">watch our own agent get attacked every hour</Link>.
            </p>
          </div>
        </section>
        <CTA />
      </main>
      <Footer />
    </div>
  );
}
