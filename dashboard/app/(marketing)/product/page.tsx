import type { Metadata } from "next";
import { publicPageMetadata } from "@/lib/site";
import Link from "next/link";
import { MarketingNav } from "@/components/marketing/nav";
import { Pillars } from "@/components/marketing/pillars";
import { FAQ, CTA, Footer } from "@/components/marketing/sections";
import { ProductIndex } from "@/components/marketing/index-grid";

export const dynamic = "force-dynamic";

// layout.tsx appends " | AgentFox", so the name is not repeated here. The previous
// description ran to 244 characters and was cut mid-clause in every search result
// and every unfurl; this one says the same six things inside the ~160 that get shown.
export const metadata: Metadata = publicPageMetadata({
  title: "AI agent security control plane",
  description:
    "Discover, govern, protect, test and prove: AI-SPM, access control, runtime guardrails, red teaming and an audit trail.",
  path: "/product",
});

/**
 * The hub.
 *
 * This was the long version — 2,157 words and nine sections, which was six
 * times a sibling page and more than half of it duplicated. Containment,
 * guardrails, discovery and assurance each have their own page now, written
 * at more depth than a shared section could carry, so keeping the old
 * sections here meant two descriptions of the same thing drifting apart.
 *
 * What a hub owes the reader is a map and an honest sentence about each
 * destination, not a précis of all eight. So: the pillar grid, which is the
 * one view of the whole product that no single page can give, a routing grid
 * built from the same `lib/marketing/nav.ts` the menu reads, and the FAQ.
 */
export default function Product() {
  return (
    <div className="mk">
      <MarketingNav />
      <main>
        <section className="mk-section mk-page-hero mk-ink-act">
          <div className="mk-wrap">
            <h1 className="mk-h1 mk-up">
              Discover, govern, protect, <em>test, prove</em>
            </h1>
            <p className="mk-lede mk-up mk-d1" style={{ marginTop: 18 }}>
              One platform for discovery, access control, runtime guardrails, red
              teaming, and an audit trail. <Link href="/playground">The playground</Link> needs no account.
            </p>
          </div>
        </section>
        {/* The map, then the routes. Everything that used to sit between
            these two is now a page of its own. */}
        <Pillars />
        <ProductIndex exclude={["/product"]} />
        <FAQ n={4} />
        <CTA />
      </main>
      <Footer />
    </div>
  );
}
