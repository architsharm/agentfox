/**
 * /research/<slug>: one accepted paper.
 *
 * Exists because Google Scholar reads `citation_*` meta tags only on a page that is
 * about a single paper and shows its abstract; /research lists three, so tags there
 * would be ignored. Records come from lib/marketing/papers.ts; an unknown slug is a 404.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { DocSection } from "@/components/lp/bench";
import { Arrow, LpFooter, LpNav } from "@/components/lp/parts";
import { bibtex, getPaper, paperPath, paperPdf, PAPERS } from "@/lib/marketing/papers";
import { absolute, publicPageMetadata } from "@/lib/site";

export const dynamicParams = false;

export function generateStaticParams() {
  return PAPERS.map((p) => ({ slug: p.slug }));
}

type Params = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const paper = getPaper((await params).slug);
  if (!paper) return {};
  return {
    ...publicPageMetadata({
      title: paper.title,
      // A search result shows about 160 characters; cut on a word, not mid-number.
      description: paper.abstract.slice(0, 157).replace(/\s+\S*$/, "") + "...",
      path: paperPath(paper.slug),
    }),
    authors: paper.authors.map((name) => ({ name })),
    // Highwire Press tags, the set Google Scholar's inclusion guidelines ask for.
    other: {
      citation_title: paper.title,
      citation_author: paper.authors,
      citation_publication_date: String(paper.year),
      citation_conference_title: `${paper.venue}, ${paper.host}`,
      citation_pdf_url: absolute(paperPdf(paper.slug)),
      citation_abstract_html_url: absolute(paperPath(paper.slug)),
    },
  };
}

export default async function PaperPage({ params }: Params) {
  const paper = getPaper((await params).slug);
  if (!paper) notFound();
  return (
    <div className="lp">
      <LpNav />
      <main id="main">
        <div className="lp-wrap lp-doc lp-onepaper">
          <p className="lp-doc-more">
            <Link href="/research">Research</Link>
          </p>
          <h1>{paper.title}</h1>
          <p className="lp-doc-lead">{paper.authors.join(", ")}</p>
          <p className="lp-doc-lead">
            Accepted at {paper.venue}, {paper.host}. {paper.when}.
          </p>
          <p>
            <a className="lp-paper-link" href={paperPdf(paper.slug)}>
              PDF, accepted version <Arrow />
            </a>
            {paper.link && (
              <>
                {" "}
                <a className="lp-paper-link" href={paper.link.href} target="_blank" rel="noreferrer">
                  {paper.link.label} <Arrow />
                </a>
              </>
            )}
          </p>

          <DocSection id="abstract" title="Abstract">
            <p>{paper.abstract}</p>
          </DocSection>

          <DocSection id="cite" title="Cite">
            <pre className="lp-paper-bib">{bibtex(paper, absolute(paperPath(paper.slug)))}</pre>
          </DocSection>
        </div>
      </main>
      <LpFooter />
    </div>
  );
}
