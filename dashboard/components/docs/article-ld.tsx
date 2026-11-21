"use client";

import { usePathname } from "next/navigation";
import { DOC_PAGES } from "@/lib/docs/pages";

/**
 * TechArticle structured data for the docs page being shown. A client component
 * only so it can read the path without making every docs page dynamic; it is
 * still rendered on the server, so the script is in the HTML a crawler fetches.
 */
export function DocsArticleLd({ siteUrl }: { siteUrl: string }) {
  const page = DOC_PAGES.find((p) => p.href === usePathname());
  if (!page) return null;
  const data = {
    "@context": "https://schema.org",
    "@type": "TechArticle",
    headline: page.title,
    description: page.description,
    url: `${siteUrl}${page.href}`,
    articleSection: page.section,
    inLanguage: "en-GB",
    author: { "@id": `${siteUrl}/#organisation` },
    publisher: { "@id": `${siteUrl}/#organisation` },
  };
  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }} />;
}
