"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { DOC_NAV } from "@/lib/docs/pages";

/**
 * The docs contents. A sticky column on desktop; on a phone it collapses behind a
 * "Contents" button that names the page you are on, because rendered in full it
 * pushed the article a whole screen down and was clipped at the fold.
 */
export function DocsSidebar() {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  // Following a link closes the drawer, so the reader lands on the article.
  useEffect(() => setOpen(false), [path]);
  const current = DOC_NAV.flatMap((s) => s.items).find((i) => i.href === path)?.label;
  return (
    <nav className={`docs-nav${open ? " is-open" : ""}`} aria-label="Docs">
      <button
        type="button"
        className="docs-nav-toggle"
        aria-expanded={open}
        aria-controls="docs-nav-list"
        onClick={() => setOpen((o) => !o)}
      >
        <span>Contents</span>
        {current && <span className="docs-nav-current">{current}</span>}
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>
      <div id="docs-nav-list" className="docs-nav-list">
        {DOC_NAV.map((section) => (
          <div key={section.heading}>
            <p>{section.heading}</p>
            <ul>
              {section.items.map((item) => (
                <li key={item.href}>
                  <Link href={item.href} aria-current={path === item.href ? "page" : undefined}>
                    {item.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </nav>
  );
}
