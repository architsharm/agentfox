import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";

import { Faq, type FaqItem } from "@/components/blog/blocks";
import { PostCard } from "@/components/blog/card";
import { MarketingNav } from "@/components/marketing/nav";
import { CTA, Footer } from "@/components/marketing/sections";
import { AUTHOR, blogPath, formatDate, relatedPosts, type BlogPost } from "@/lib/blog";
import { absolute, SITE_NAME } from "@/lib/site";

export type TocItem = { id: string; label: string };

/**
 * One shape for every post: what it is about, the argument, where to go next.
 *
 * The right rail carries two things a reader of a long page needs and a docs
 * page already gives them: where they are in it, and the product pages this
 * post is the argument for. The second is the internal link a search engine
 * follows from a post that ranks to the page that should.
 */
export function BlogArticle({
  post,
  toc,
  faq,
  children,
}: {
  post: BlogPost;
  toc: TocItem[];
  faq: FaqItem[];
  children: ReactNode;
}) {
  const related = relatedPosts(post);
  return (
    <div className="mk">
      <JsonLd post={post} faq={faq} />
      <MarketingNav />
      <main>
        <section className="mk-section-tight blog-hero mk-ink-act">
          <div className="mk-hero-glow" aria-hidden />
          <div className="mk-wrap" style={{ position: "relative" }}>
            <nav className="blog-crumbs mk-up mk-d1" aria-label="Breadcrumb">
              <Link href="/blog">Blog</Link>
              <span aria-hidden>/</span>
              <span>{post.tag}</span>
            </nav>
            <h1 className="blog-title mk-up mk-d2">{post.title}</h1>
            <p className="mk-lede blog-lede mk-up mk-d3">{post.description}</p>
            <p className="blog-meta mk-up mk-d4">
              <span>{AUTHOR.name}</span>
              <span aria-hidden>·</span>
              <time dateTime={post.published}>{formatDate(post.published)}</time>
              <span aria-hidden>·</span>
              <span>{post.readMinutes} min read</span>
            </p>
          </div>
        </section>

        <div className="mk-wrap blog-cover">
          <div className="shot-frame">
            <Image
              src={post.image.src}
              alt={post.image.alt}
              width={post.image.width}
              height={post.image.height}
              priority
              sizes="(max-width: 1100px) 100vw, 1080px"
            />
          </div>
        </div>

        <div className="mk-wrap blog-layout">
          <article className="docs-doc blog-prose">
            {children}
            <Faq items={faq} />
          </article>

          <aside className="blog-rail" aria-label="On this page">
            <div className="blog-rail-sticky">
              <p className="blog-rail-head">On this page</p>
              <ol className="blog-toc">
                {toc.map((item) => (
                  <li key={item.id}>
                    <a href={`#${item.id}`}>{item.label}</a>
                  </li>
                ))}
                <li>
                  <a href="#faq">Questions</a>
                </li>
              </ol>
              <p className="blog-rail-head" style={{ marginTop: 28 }}>
                In the product
              </p>
              <ul className="blog-pillars">
                {post.pillars.map((p) => (
                  <li key={p.href}>
                    <Link href={p.href}>
                      <b>{p.label}</b>
                      <span>{p.why}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          </aside>
        </div>

        <section className="mk-section mk-paper-act blog-next">
          <div className="mk-wrap">
            <div className="blog-next-head">
              <h2 className="mk-h2">Keep reading</h2>
              <Link href="/blog" className="mk-btn mk-btn-outline">
                All posts
              </Link>
            </div>
            <div className="blog-grid">
              {related.map((p) => (
                <PostCard key={p.slug} post={p} />
              ))}
            </div>
          </div>
        </section>
        <CTA />
      </main>
      <Footer />
    </div>
  );
}

/**
 * BlogPosting, BreadcrumbList and FAQPage, as one graph.
 *
 * Every field is something the page itself shows: the headline is the H1, the
 * FAQ answers are the strings rendered in the FAQ, the image is the cover. A
 * search engine that is told something the reader cannot see treats it as spam.
 */
function JsonLd({ post, faq }: { post: BlogPost; faq: FaqItem[] }) {
  const url = absolute(blogPath(post.slug));
  const graph = [
    {
      "@type": "BlogPosting",
      "@id": `${url}#article`,
      headline: post.title,
      description: post.description,
      url,
      mainEntityOfPage: url,
      datePublished: post.published,
      dateModified: post.updated ?? post.published,
      image: absolute(post.image.src),
      keywords: post.keywords.join(", "),
      articleSection: post.tag,
      inLanguage: "en-GB",
      author: { "@type": "Organization", name: AUTHOR.name, url: AUTHOR.url },
      publisher: {
        "@type": "Organization",
        name: SITE_NAME,
        url: absolute("/"),
        logo: { "@type": "ImageObject", url: absolute("/icon.png") },
      },
    },
    {
      "@type": "BreadcrumbList",
      itemListElement: [
        { "@type": "ListItem", position: 1, name: SITE_NAME, item: absolute("/") },
        { "@type": "ListItem", position: 2, name: "Blog", item: absolute("/blog") },
        { "@type": "ListItem", position: 3, name: post.title, item: url },
      ],
    },
    {
      "@type": "FAQPage",
      mainEntity: faq.map((item) => ({
        "@type": "Question",
        name: item.q,
        acceptedAnswer: { "@type": "Answer", text: item.a },
      })),
    },
  ];
  return (
    <script
      type="application/ld+json"
      // JSON.stringify does not escape "<", and a "</script>" inside any string
      // would end the tag early. None of ours contain one; this keeps it so.
      dangerouslySetInnerHTML={{
        __html: JSON.stringify({ "@context": "https://schema.org", "@graph": graph }).replace(
          /</g,
          "\\u003c",
        ),
      }}
    />
  );
}
