import type { Metadata } from "next";
import Link from "next/link";

import { LpFooter, LpNav } from "@/components/lp/parts";

export const metadata: Metadata = { title: "Page not found", robots: { index: false, follow: true } };

/**
 * A URL that matches no route at all, and the fallback for any `notFound()` a
 * page throws without its own boundary.
 *
 * It renders under the root layout, not the app shell, so most of the people who
 * meet it are on the public site: a mistyped docs link, an old blog URL, a link
 * from somewhere else. It therefore wears the public header and footer and speaks
 * to a visitor, with the way back to the dashboard as one of the options rather
 * than the only one.
 *
 * Pages that know what kind of record is missing should keep using the
 * `NotFound` component in components/ui/index.tsx instead: "no finding at this id" is
 * a more useful sentence than "no such page".
 */
export default function NotFound() {
  return (
    <div className="lp" style={{ display: "flex", flexDirection: "column" }}>
      <LpNav />
      <main className="lp-page" style={{ flex: 1 }}>
        <div className="lp-wrap">
          <span className="lp-pill">404</span>
          <h1 style={{ marginTop: 20 }}>This page doesn&apos;t exist</h1>
          <p className="lp-lead">
            The link may be old, or the page has moved. The docs and the home page are the best places to pick up from.
          </p>
          <div className="lp-actions" style={{ justifyContent: "flex-start", marginTop: 32 }}>
            <Link href="/" className="lp-btn lp-btn-primary lp-btn-sm">
              Home
            </Link>
            <Link href="/docs" className="lp-btn lp-btn-secondary lp-btn-sm">
              Docs
            </Link>
            <Link href="/app" className="lp-btn lp-btn-secondary lp-btn-sm">
              Dashboard
            </Link>
          </div>
        </div>
      </main>
      <LpFooter />
    </div>
  );
}
