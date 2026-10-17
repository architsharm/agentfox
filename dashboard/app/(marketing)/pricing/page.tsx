import type { Metadata } from "next";
import Link from "next/link";
import { publicPageMetadata, SUPPORT_EMAIL } from "@/lib/site";
import { MarketingNav } from "@/components/marketing/nav";
import { Footer } from "@/components/marketing/sections";
import { Editions, OpenSourcePromise, WhyOpen } from "@/components/marketing/editions";

export const dynamic = "force-dynamic";

/**
 * /pricing exists because a visitor and a crawler both look for it, and a site with
 * no such URL reads as a site hiding the answer.
 *
 * Deliberately almost no copy of its own. `Editions` and `WhyOpen` in
 * components/marketing/editions.tsx are the single source of truth for every
 * commercial claim, and the homepage renders the same two components. Writing a
 * second set of words here is how the homepage and this page end up disagreeing
 * about what is free, and the one under an editor's eye is never the stale one.
 *
 * Everything those components say was checked against the repository, with the
 * sources listed in that file's own header comment: Apache-2.0 in LICENSE, no
 * billing or licence-key code under src/agentfox/, and managed cloud described as in
 * development everywhere it appears because it does not exist.
 *
 * No price appears here for the same reason it appears nowhere else: there isn't
 * one.
 */

export const metadata: Metadata = publicPageMetadata({
  title: "Pricing and editions",
  description:
    "Everything is Apache-2.0 and free to self-host forever, with nothing gated. The hosted version is open and free while in preview: sign in with GitHub, no card.",
  path: "/pricing",
});

export default async function Pricing({
  searchParams,
}: {
  searchParams: Promise<{ waitlist_notice?: string; waitlist_error?: string }>;
}) {
  const { waitlist_notice, waitlist_error } = await searchParams;
  return (
    <div className="mk">
      <MarketingNav />
      <main>
        <section className="mk-section mk-page-hero mk-ink-act">
          <div className="mk-wrap">
            <h1 className="mk-h1 mk-up mk-d1">
              Free to self-host, <em>forever</em></h1>
            <p className="mk-lede mk-up mk-d2" style={{ marginTop: 20 }}>
              Free to self-host, under Apache-2.0. The hosted preview is free while
              it lasts, and nothing on this site is priced.
            </p>
            <p className="mk-fine mk-up mk-d3" style={{ marginTop: 18 }}>
              Questions about a rollout? <a href={`mailto:${SUPPORT_EMAIL}`}>{SUPPORT_EMAIL}</a>, or
              see <Link href="/support">how to get help</Link>.
            </p>
          </div>
        </section>
        <Editions notice={waitlist_notice} error={waitlist_error} />
        <OpenSourcePromise />
        <WhyOpen />
      </main>
      <Footer />
    </div>
  );
}
