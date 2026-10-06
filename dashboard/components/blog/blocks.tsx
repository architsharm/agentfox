import Link from "next/link";
import type { ReactNode } from "react";

import { Shot } from "@/components/marketing/shot";

/**
 * The pieces a post is written in.
 *
 * Posts render inside `.docs-doc`, so headings, lists, tables, code and inline
 * links look exactly as they do in the docs a reader clicks through to. These
 * are only the blocks a post needs and a docs page does not: a framed figure,
 * the summary up top, a call to action mid-article, and the FAQ.
 */

/** A screenshot or diagram, framed and captioned. Wider than the text column. */
export function Figure({
  src,
  alt,
  caption,
  width,
  height,
  priority,
}: {
  src: string;
  alt: string;
  caption: ReactNode;
  width: number;
  height: number;
  priority?: boolean;
}) {
  return (
    <div className="blog-figure">
      <Shot
        src={src}
        alt={alt}
        caption={caption}
        width={width}
        height={height}
        priority={priority}
        sizes="(max-width: 900px) 100vw, 820px"
      />
    </div>
  );
}

/** A drawn figure: inline SVG or HTML, framed like a screenshot. */
export function Diagram({ caption, children, label }: { caption: ReactNode; children: ReactNode; label: string }) {
  return (
    <figure className="blog-figure blog-diagram" role="group" aria-label={label}>
      <div className="blog-diagram-frame">{children}</div>
      <figcaption>{caption}</figcaption>
    </figure>
  );
}

/**
 * The answer, before the argument.
 *
 * A reader from search decides in about ten seconds whether this page has what
 * they came for, and a list of three plain sentences is also what a search
 * engine lifts into a snippet.
 */
export function Takeaways({ items }: { items: ReactNode[] }) {
  return (
    <aside className="blog-takeaways" aria-label="Key takeaways">
      <p className="blog-takeaways-head">In short</p>
      <ul>
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </aside>
  );
}

/**
 * One offer, mid-article, where the reader has just been told the thing it
 * lets them do. Deliberately a link and not a form: nothing here asks for an
 * email.
 */
export function InlineCTA({
  title,
  body,
  href,
  label,
  secondary,
}: {
  title: string;
  body: ReactNode;
  href: string;
  label: string;
  secondary?: { href: string; label: string };
}) {
  return (
    <aside className="blog-cta">
      <div>
        <p className="blog-cta-title">{title}</p>
        <p className="blog-cta-body">{body}</p>
      </div>
      <div className="blog-cta-actions">
        <Link href={href} className="mk-btn mk-btn-primary">
          {label}
        </Link>
        {secondary && (
          <Link href={secondary.href} className="mk-btn mk-btn-outline">
            {secondary.label}
          </Link>
        )}
      </div>
    </aside>
  );
}

/**
 * A number the post rests on, with where it came from directly underneath.
 * The source line is not optional, for the same reason it is not on /benchmark.
 */
export function Stat({ value, label, source }: { value: string; label: ReactNode; source: ReactNode }) {
  return (
    <div className="blog-stat">
      <span className="blog-stat-value">{value}</span>
      <span className="blog-stat-label">{label}</span>
      <span className="blog-stat-source">{source}</span>
    </div>
  );
}

export function StatRow({ children }: { children: ReactNode }) {
  return <div className="blog-stats">{children}</div>;
}

export type FaqItem = { q: string; a: string };

/**
 * The FAQ, as plain text on purpose: the same strings go into the FAQPage
 * structured data, and what a search engine is told must be what the page says.
 */
export function Faq({ items }: { items: FaqItem[] }) {
  return (
    <section className="blog-faq" aria-labelledby="faq">
      <h2 id="faq">Frequently asked questions</h2>
      {items.map((item) => (
        <details key={item.q}>
          <summary>{item.q}</summary>
          <p>{item.a}</p>
        </details>
      ))}
    </section>
  );
}
