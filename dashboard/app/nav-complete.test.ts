/**
 * Every public page is in the information architecture.
 *
 * Deriving the nav, footer, sitemap and llms.txt from `lib/marketing/nav.ts` removed one
 * class of bug — those four can no longer disagree — and introduced a
 * different one: a page can now exist on disk, be routable, be public, and
 * appear in none of them, because nothing forces a new `app/x/page.tsx` to be
 * registered.
 *
 * That is a worse failure than the one it replaced. The old bug was a page
 * missing from one of four files; this one is a page missing from all of
 * them, reachable only by typing the URL. So it is checked against the
 * filesystem rather than against another list.
 */

import { readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { ALL_PAGES, ALL_PATHS } from "@/lib/marketing/nav";

const APP = join(process.cwd(), "app");

/**
 * Routes that are public and routable but deliberately not in the IA.
 *
 * Each needs a reason, because "add it to the exceptions" is how this test
 * stops working.
 */
const NOT_IN_NAV = new Set([
  // Public and crawlable so the `noindex` on the page itself can be read, but
  // a sitemap is a list of URLs you want indexed and this page asks not to be.
  "/login",
  // The signed-in application. Private, behind middleware.
  "/app",
]);

/** Directory names Next.js does not turn into a plain public path. */
function isRouteDir(name: string): boolean {
  return !name.startsWith("_") && !name.startsWith(".") && !name.startsWith("(");
}

/** `(marketing)`, `(product)`: organise files without adding a URL segment. */
function isRouteGroup(name: string): boolean {
  return name.startsWith("(") && name.endsWith(")");
}

function publicPageRoutes(dir: string = APP): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir)) {
    const sub = join(dir, entry);
    if (!statSync(sub).isDirectory()) continue;
    // A route group is transparent: its top-level pages are top-level URLs.
    if (isRouteGroup(entry)) {
      found.push(...publicPageRoutes(sub));
      continue;
    }
    if (!isRouteDir(entry)) continue;
    // Only top-level pages. A nested route is reached from its parent, which
    // is the page that has to be in the nav.
    const hasPage = readdirSync(sub).some((f) => f === "page.tsx" || f === "page.ts");
    if (hasPage) found.push(`/${entry}`);
  }
  return found.sort();
}

describe("the information architecture", () => {
  it("names every public page that exists on disk", () => {
    const known = new Set(ALL_PATHS);
    const missing = publicPageRoutes().filter((r) => !known.has(r) && !NOT_IN_NAV.has(r));
    expect(
      missing,
      `these pages exist and are in no menu, sitemap or llms.txt — add them to lib/marketing/nav.ts ` +
        `(or to NOT_IN_NAV with a reason): ${missing.join(", ")}`,
    ).toEqual([]);
  });

  it("does not name a page that does not exist", () => {
    const onDisk = new Set([...publicPageRoutes(), "/"]);
    const phantom = ALL_PATHS.filter((p) => !onDisk.has(p));
    expect(phantom, `lib/marketing/nav.ts links to pages with no route: ${phantom.join(", ")}`).toEqual(
      [],
    );
  });

  it("gives every entry a note, because the menu renders it", () => {
    // A blank note renders as an empty line under a menu label, which looks
    // like a bug and reads as one.
    const blank = ALL_PAGES.filter((p) => !p.note || p.note.trim().length < 12);
    expect(blank.map((p) => p.href)).toEqual([]);
  });
});
