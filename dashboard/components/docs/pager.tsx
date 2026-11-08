"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { DOC_PAGES } from "@/lib/docs/pages";

/**
 * Previous and next page, from the page's place in the sidebar. The docs read in order,
 * so the foot of every page says where the path goes next.
 */
export function DocsPager() {
  const path = usePathname();
  const at = DOC_PAGES.findIndex((page) => page.href === path);
  if (at < 0) return null;
  const prev = DOC_PAGES[at - 1];
  const next = DOC_PAGES[at + 1];
  return (
    <nav className="docs-pager" aria-label="Previous and next page">
      {prev ? (
        <Link href={prev.href} className="docs-pager-prev">
          <span>Previous</span>
          {prev.title}
        </Link>
      ) : (
        <span />
      )}
      {next && (
        <Link href={next.href} className="docs-pager-next">
          <span>Next</span>
          {next.title}
        </Link>
      )}
    </nav>
  );
}

/** The section a page sits in ("Govern", "Reference"), shown above its title. */
export function DocsKicker() {
  const path = usePathname();
  const page = DOC_PAGES.find((p) => p.href === path);
  return page ? <p className="docs-kicker">{page.section}</p> : null;
}
