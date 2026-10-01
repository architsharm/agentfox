import Link from "next/link";

import { PRODUCT } from "@/lib/nav";

/**
 * The routing grid on /product.
 *
 * Built from `lib/nav.ts`, so the hub and the header menu cannot describe
 * the same page differently — which they did within a day of the pages
 * existing, because the hub had its own copy of the words.
 *
 * It uses `summary` rather than `note`: the menu line is six words because a
 * menu has no room, and a card does. Same source, the longer field.
 */
export function ProductIndex({ exclude = [] }: { exclude?: string[] } = {}) {
  // A hub that links to itself is a dead end dressed as a route. /product
  // passes its own path, and "How it works" stays because it is a different
  // page rather than this one.
  const skip = new Set(exclude);
  return (
    <section className="mk-section mk-band mk-reveal">
      <div className="mk-wrap">
        <div className="mk-narrow">
          <h2 className="mk-h2">The platform, in depth</h2>
          <p className="mk-lede" style={{ marginTop: 16 }}>
            One page for each part of the product.
          </p>
        </div>

        {PRODUCT.sections
          .map((section) => ({
            ...section,
            items: section.items.filter((item) => !skip.has(item.href)),
          }))
          .filter((section) => section.items.length > 0)
          .map((section, i) => (
          <div key={section.heading ?? i} className="idx-group">
            {section.heading && <p className="mk-label">{section.heading}</p>}
            <div className="idx-grid mk-stagger">
              {section.items.map((item) => (
                <Link key={item.href} href={item.href} className="idx-card">
                  <b>{item.label}</b>
                  <span>{item.summary ?? item.note}</span>
                  <i aria-hidden>&rarr;</i>
                </Link>
              ))}
            </div>
            </div>
          ))}
      </div>
    </section>
  );
}
