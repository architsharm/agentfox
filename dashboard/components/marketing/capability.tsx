import Link from "next/link";
import type { ReactNode } from "react";

import { MarketingNav } from "@/components/marketing/nav";
import { CTA, Footer } from "@/components/marketing/sections";
import { PRODUCT } from "@/lib/marketing/nav";

/**
 * One shape for every "what it does" page.
 *
 * A template rather than five bespoke pages, for the same reason the
 * reference site templates theirs: these five answer the same four questions
 * in the same order — what goes wrong, what we do about it in steps, what we
 * still do not do, and where to go next — and five hand-built variations on
 * that would differ in ways that carry no meaning and drift apart within a
 * month.
 *
 * The part that is not borrowed is `gaps`. It is a required prop, not an
 * optional one: a capability page with nothing in that field does not
 * compile, which is the only way a section like that survives contact with
 * someone writing marketing copy in a hurry.
 */

export type Step = { title: string; body: ReactNode };

export type CapabilityPageProps = {
  kicker: string;
  /** Two parts, so the second can carry the accent. */
  title: [string, string];
  lede: string;
  /** Where the commands for this page live. Marketing pages do not print them. */
  docs?: string;
  challenge: ReactNode;
  /**
   * The one thing this page is really about, rendered full width between the
   * problem and the steps.
   *
   * Every page keeps the same skeleton — problem, feature, steps, gaps,
   * related — and spends its difference here. Before this slot existed the
   * three pages with a distinctive centrepiece had bespoke layouts around it
   * and the other five shared a template, so eight sibling pages read as two
   * unrelated sets.
   */
  feature?: { title: string; lede?: string; body: ReactNode };
  steps: Step[];
  /** What this does not do. Required. */
  gaps: { title: string; body: ReactNode };
  /** Paths into lib/marketing/nav's PRODUCT group; the label and note are read from there. */
  related: string[];
};

const BY_HREF = new Map(
  PRODUCT.sections.flatMap((s) => s.items).map((item) => [item.href, item]),
);

export function CapabilityPage({
  kicker,
  title,
  lede,
  docs,
  challenge,
  feature,
  steps,
  gaps,
  related,
}: CapabilityPageProps) {
  return (
    <div className="mk">
      <MarketingNav />
      <main>
        {/* The hero animates on load rather than on scroll: it is already in
            view, and an IntersectionObserver firing on something the reader
            is looking at reads as a flicker. Same staggered classes the home
            hero uses, so the two do not arrive differently. */}
        {/* Paper, like the homepage hero, so a reader moving between them
            feels one site. */}
        <section className="mk-section cap-hero mk-ink-act">
          <div className="mk-hero-glow" aria-hidden />
          <div className="mk-wrap" style={{ position: "relative" }}>
            <p className="mk-kicker mk-up mk-d1">{kicker}</p>
            <h1 className="mk-h1 mk-up mk-d2" style={{ marginTop: 14 }}>
              {title[0]} <em>{title[1]}</em>
            </h1>
            <p className="mk-lede mk-up mk-d3" style={{ marginTop: 20 }}>
              {lede}
            </p>
            {docs && (
              <p className="mk-fine mk-up mk-d4" style={{ marginTop: 18 }}>
                <Link href={docs}>Commands and setup</Link>
              </p>
            )}
          </div>
        </section>

        <section className="mk-section-tight mk-reveal">
          <div className="mk-wrap">
            <div className="cap-challenge">
              <p className="mk-label">The problem</p>
              <div className="mk-body">{challenge}</div>
            </div>
          </div>
        </section>

        {feature && (
          /* The centrepiece takes ink, exactly as the platform section does
             on the homepage: it is the one thing this page is really about,
             and it should read as the page's dark act. */
          <section className="mk-section mk-ink-act mk-reveal">
            <div className="mk-wrap">
              <div className="mk-narrow">
                <h2 className="mk-h2">{feature.title}</h2>
                {feature.lede && (
                  <p className="mk-lede" style={{ marginTop: 16 }}>
                    {feature.lede}
                  </p>
                )}
              </div>
              {feature.body}
            </div>
          </section>
        )}

        <section
          className={feature ? "mk-section mk-reveal" : "mk-section mk-ink-act mk-reveal"}
        >
          <div className="mk-wrap">
            <ol className="cap-steps mk-stagger">
              {steps.map((step, i) => (
                <li key={step.title}>
                  {/* Numbered because these are a sequence, not a feature
                      grid — each step assumes the one above it happened. */}
                  <span className="cap-step-n">{String(i + 1).padStart(2, "0")}</span>
                  <div className="cap-step-body">
                    <h2>{step.title}</h2>
                    <div className="mk-body">{step.body}</div>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* The limits and the way out, on paper. A page that ended on the
            same white as its middle has no full stop. */}
        <section className="mk-section mk-paper-act mk-reveal">
          <div className="mk-wrap">
            <div className="mk-honest">
              <div>
                <h2 className="mk-h3">{gaps.title}</h2>
                <div className="mk-body">{gaps.body}</div>
              </div>
              <Link href="/coverage" className="mk-btn mk-btn-outline">
                Every gap, scored
              </Link>
            </div>

            <div className="cap-related mk-stagger">
              {related.map((href) => {
                const item = BY_HREF.get(href);
                if (!item) return null;
                return (
                  <Link key={href} href={href} className="cap-related-item">
                    <b>{item.label}</b>
                    <span>{item.note}</span>
                  </Link>
                );
              })}
            </div>
          </div>
        </section>
        <CTA />
      </main>
      <Footer />
    </div>
  );
}
