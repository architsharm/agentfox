"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

/**
 * Gives every table cell its column's name (`data-label`) and marks each row's
 * first wide cell as its title (`data-primary`). On a phone af-theme.css turns those
 * tables into stacked rows: short cells (`.tight`: time, severity, outcome) as a line
 * of chips, the title in full, and every other cell under its column's name. Without
 * the names a stacked "3" or "2m ago" means nothing. Desktop ignores both attributes.
 */
export function TableLabels() {
  const pathname = usePathname();
  useEffect(() => {
    const label = () => {
      for (const table of document.querySelectorAll<HTMLTableElement>("main table")) {
        const names = [...table.querySelectorAll("thead th")].map((th) => th.textContent?.trim() ?? "");
        for (const row of table.querySelectorAll<HTMLTableRowElement>("tbody tr")) {
          let primary = false;
          [...row.cells].forEach((cell, i) => {
            if (names[i] && cell.dataset.label !== names[i]) cell.dataset.label = names[i];
            if (!primary && !cell.classList.contains("tight") && cell.colSpan === 1) {
              cell.dataset.primary = "";
              primary = true;
            }
          });
        }
      }
    };
    // Not before React has hydrated the server's HTML: an attribute added first is a
    // hydration mismatch. So wait for the page to load, then a beat more.
    let seen: MutationObserver | null = null;
    let wait = 0;
    const start = () => {
      label();
      const main = document.querySelector("main");
      if (!main) return;
      // Tables arrive late (streamed, filtered, paged): label them as they do.
      seen = new MutationObserver(label);
      seen.observe(main, { childList: true, subtree: true });
    };
    const later = () => {
      wait = window.setTimeout(start, 400);
    };
    if (document.readyState === "complete") later();
    else window.addEventListener("load", later, { once: true });
    return () => {
      window.removeEventListener("load", later);
      window.clearTimeout(wait);
      seen?.disconnect();
    };
  }, [pathname]);
  return null;
}
