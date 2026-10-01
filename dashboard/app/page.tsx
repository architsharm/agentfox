import type { Metadata } from "next";
import { CATEGORY_CAP } from "./how-it-works/_public";
import { SITE_URL, SUPPORT_EMAIL, publicPageMetadata, HOME_TITLE, HOME_DESCRIPTION } from "@/lib/site";
import { MarketingNav, REPO } from "@/components/marketing/nav";
import { CTA, Footer } from "@/components/marketing/sections";
import { Platform } from "@/components/marketing/platform";
import {
  Hero,
  Origins,
  Boundaries,
  Proof,
  Limits,
} from "@/components/marketing/home";

export const dynamic = "force-dynamic";

/**
 * layout.tsx's title template appends " | AgentFox" to a child page's title. This
 * page is the one that must not take it: "AgentFox: ... | AgentFox" says the name
 * twice inside a 60-character budget, so `title.absolute` opts out.
 *
 * The description drops the previous one's "even after a prompt injection has
 * convinced the model" clause only for length: at 191 characters it was cut off in
 * the result snippet, which is where the sentence needs to land whole.
 */
export const metadata: Metadata = {
  ...publicPageMetadata({
    title: HOME_TITLE,
    description: HOME_DESCRIPTION,
    path: "/",
  }),
  // `absolute` opts this one page out of layout.tsx's "%s | AgentFox" template.
  title: { absolute: HOME_TITLE },
};

/**
 * Structured data for the landing page.
 *
 * Two objects in one `@graph`, because they describe two different things that
 * point at each other: the software, and whoever publishes it.
 *
 * Every property below is a fact checked against a file in this repository, and
 * nothing that could not be checked is here:
 *
 *   - `license` / "Apache-2.0" ............ LICENSE at the repository root
 *   - `codeRepository` / `url` ............ components/marketing/nav.tsx REPO
 *   - `email` ............................. components/marketing/editions.tsx
 *   - `description` ....................... app/how-it-works/_public.tsx CATEGORY
 *   - `offers` price 0 .................... it is Apache-2.0 source; the free
 *                                           edition is what this page describes
 *   - `applicationCategory` / `os` ........ "runs offline with no API key",
 *                                           components/marketing/hero.tsx
 *
 * Deliberately absent: `aggregateRating`, `review`, `ratingValue`, any user or
 * customer count, and any price other than zero. This project has no ratings and
 * no published customers, and invented review markup is the single most common
 * cause of a Google manual action against structured data. A rich result bought
 * with a fabricated number is worth less than no rich result.
 *
 * `SoftwareApplication` rather than `SoftwareSourceCode`: both fit an open-source
 * control plane, but the thing a reader is looking for here is a product they can
 * run, and `SoftwareApplication` is the type that carries `offers` and
 * `operatingSystem`. `codeRepository` keeps the source side of it addressable.
 */
function LandingJsonLd() {
  const graph = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "SoftwareApplication",
        "@id": `${SITE_URL}/#software`,
        name: "AgentFox",
        applicationCategory: "SecurityApplication",
        applicationSubCategory: "AI agent governance and security control plane",
        description: CATEGORY_CAP,
        url: SITE_URL,
        operatingSystem: "Linux, macOS, Windows",
        license: "https://www.apache.org/licenses/LICENSE-2.0",
        codeRepository: REPO,
        isAccessibleForFree: true,
        offers: {
          "@type": "Offer",
          price: "0",
          priceCurrency: "USD",
          availability: "https://schema.org/InStock",
        },
        publisher: { "@id": `${SITE_URL}/#organisation` },
      },
      {
        "@type": "Organization",
        "@id": `${SITE_URL}/#organisation`,
        name: "AgentFox",
        url: SITE_URL,
        logo: `${SITE_URL}/apple-icon.png`,
        sameAs: [REPO],
        contactPoint: {
          "@type": "ContactPoint",
          contactType: "customer support",
          email: SUPPORT_EMAIL,
          url: `${SITE_URL}/`,
        },
      },
    ],
  };

  return (
    <script
      type="application/ld+json"
      // JSON.stringify, not a template literal: it is the only thing that escapes
      // a quote or a newline that ever ends up in one of these strings correctly.
      dangerouslySetInnerHTML={{ __html: JSON.stringify(graph) }}
    />
  );
}

/* --- Public landing page --------------------------------------------------
 *
 * "/" is the URL a launch audience arrives at, and a signed-out visitor sees this
 * instead of a sign-in wall. The two things that need no account (the playground
 * and the benchmark evidence) are the two things it points at hardest.
 *
 * The page is composed entirely from components/marketing/*, which carry their own
 * stylesheet (app/marketing.css, the `.mk-*` layer) so the marketing surface and the
 * signed-in app can each look right without either one constraining the other. The
 * design language is the one this team already ships on dayotter.com.
 *
 * Every figure in those sections is copied from README.md or app/benchmark/page.tsx,
 * both of which name the results file each number comes from. Nothing is restated
 * from memory, and anything needing a new number links to /benchmark instead.
 */

function Landing() {
  return (
    <div className="mk">
      {/* Inside the signed-out branch only. The signed-in Overview at this same URL
          is a private dashboard, and marking it up as a product page would be
          describing the wrong document. */}
      <LandingJsonLd />
      <MarketingNav />
      <main className="mk-home">
        {/* Benefit, proof, price, honesty. Each section states what the reader gets
            and then shows it, and no two adjacent sections have the same shape.

            The order is the order a sceptic reads in: what is it, does it fit my
            stack, what does it actually do for me, is any of that true, what does it
            cost, and what will go wrong. The limits are near the end on purpose:
            they are the last thing a buyer checks and the first thing a competitor
            quotes, so they are ours to state plainly rather than theirs to find. */}
        {/* Four sections, not nine. A copy audit of the rendered text found 32
            verbatim blocks shared between this page and /product — the whole
            rollout sequence, the whole FAQ, the whole pricing table — which is
            why the page ran to 8,016px and 1,464 words. A reader who wants the
            rollout steps is a reader who has already decided; they can click
            through. Rollout and the FAQ now live only on /product, the editions
            table only on /pricing. */}
        {/* Two sections added after reading the competitor pages that a
            stranger could follow fastest. Both are legibility, not features.

            `Origins` names the kinds of failure in plain sentences before any
            mechanism appears — the page previously went from "runtime
            firewall" straight to a three-stage worked example, which asks the
            reader to already believe there is a problem worth three stages.

            `ControlPoints` replaces nothing and says the thing the README
            buried: six binding points, one policy set. It sits right after
            the stack strip because "does it fit my stack" and "do I have to
            re-architect" are the same question asked twice, and it also
            carries the observe-mode line, which was shipped a year ago and
            mentioned on no public page. */}
        <Hero />
        <Origins />
        <Platform />
        <Boundaries />
        <Proof />
        <Limits />
        <CTA />
      </main>
      <Footer />
    </div>
  );
}

export default function Home() {
  return <Landing />;
}
