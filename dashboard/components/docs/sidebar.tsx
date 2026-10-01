"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { DOC_NAV } from "@/lib/docs";

export function DocsSidebar() {
  const path = usePathname();
  return (
    <nav className="docs-nav" aria-label="Docs">
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
    </nav>
  );
}
