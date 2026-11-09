import type { Metadata } from "next";
import { CATEGORY_CAP } from "@/lib/marketing/category";
import { SITE_URL, SUPPORT_EMAIL, publicPageMetadata, HOME_TITLE, HOME_DESCRIPTION } from "@/lib/site";
import { REPO } from "@/components/marketing/nav";
import { Production } from "@/components/lp/Production";


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
    ownImage: true,
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
 *   - `description` ....................... app/(marketing)/how-it-works/_public.tsx CATEGORY
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
 * "/" is the URL a launch audience arrives at. It sells one theme: guardrails
 * that don't block your real customers (components/lp/Production.tsx). The rest
 * of the platform is one section on that page, and the whole site map is in its
 * footer, so every page the old landing linked to is still one click away.
 */

export default function Home() {
  return (
    <>
      <LandingJsonLd />
      <Production />
    </>
  );
}
