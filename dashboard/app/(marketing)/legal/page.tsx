import type { Metadata } from "next";
import Link from "next/link";
import { MarketingNav } from "@/components/marketing/nav";
import { Footer } from "@/components/marketing/sections";
import { publicPageMetadata, REPO_URL, SUPPORT_EMAIL } from "@/lib/site";

export const dynamic = "force-dynamic";

/**
 * A hub, not a document. Five destinations and one line each saying what a reader
 * will find there, so nobody has to open three of them to discover which one they
 * wanted. Anything longer belongs on the page it links to.
 */
export const metadata: Metadata = publicPageMetadata({
  title: "Legal",
  description:
    "Privacy, terms, security disclosure, the Apache-2.0 licence and third-party notices, with a line on each saying what you will find before you open it.",
  path: "/legal",
});

const SRC = `${REPO_URL}/blob/main`;

type Row = { title: string; href: string; external?: boolean; blurb: string };

const ROWS: Row[] = [
  {
    title: "Privacy",
    href: "/privacy",
    blurb:
      "What the hosted playground and GitHub sign-in store, how long a sandbox lives, the two cookies, the three sub-processors, and why a copy you run yourself sends us nothing.",
  },
  {
    title: "Terms",
    href: "/terms",
    blurb:
      "Terms for the hosted service only: as-is, no SLA, a shared playground that gets reset, what you may and may not attack, and an explicit statement that none of it narrows the licence.",
  },
  {
    title: "Security",
    href: "/security",
    blurb:
      "How to report a vulnerability, what counts as one, the properties enforced in code, and an unhedged account of what nobody outside this project has ever verified.",
  },
  {
    title: "Licence: Apache-2.0",
    href: `${SRC}/LICENSE`,
    external: true,
    blurb:
      "The licence for the software itself. Use it, modify it, run it commercially, distribute your changes. This is the grant the terms page promises not to touch.",
  },
  {
    title: "Third-party notices",
    href: `${SRC}/THIRD_PARTY_NOTICES.md`,
    external: true,
    blurb:
      "Every project AgentFox incorporates or optionally integrates, with its licence and what it is used for, satisfying the attribution requirement in Apache-2.0 section 4(d).",
  },
];

export default function Legal() {
  return (
    <div className="mk">
      <MarketingNav />
      <main>
        <section className="mk-section mk-page-hero mk-ink-act">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <span className="mk-eyebrow">Legal</span>
              <h1 className="mk-h1" style={{ margin: "18px 0 0" }}>
                Legal</h1>
              <p className="mk-lede" style={{ marginTop: 20 }}>
                Terms for the hosted service. The software is Apache-2.0, and running
                it does not require agreeing to these.
              </p>
            </div>
          </div>
        </section>

        <section className="mk-section">
          <div className="mk-wrap">
              <div className="mk-grid mk-grid-2">
                {ROWS.map((row) => (
                  <div className="mk-card" key={row.href}>
                    <h2 className="mk-h3">
                      {row.external ? (
                        <a href={row.href} target="_blank" rel="noreferrer">
                          {row.title}
                        </a>
                      ) : (
                        <Link href={row.href}>{row.title}</Link>
                      )}
                    </h2>
                    <p className="mk-body" style={{ margin: "8px 0 0", fontSize: "var(--t-body)" }}>
                      {row.blurb}
                    </p>
                  </div>
                ))}
              </div>

              <p className="mk-fine" style={{ marginTop: 30 }}>
                Anything not covered by one of those:{" "}
                <a href={`mailto:${SUPPORT_EMAIL}`}>{SUPPORT_EMAIL}</a>. Vulnerabilities do
                not go to that address; the route for those is on the{" "}
                <Link href="/security">security page</Link>.
              </p>
          </div>
        </section>
      </main>
      <Footer />
    </div>
  );
}
