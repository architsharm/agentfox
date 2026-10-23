"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

/**
 * The sidebar's "Menu" button, shown on phones only (see af-theme.css). On a narrow
 * screen the sidebar is a top bar: the mark, the project switcher and this button;
 * the nav itself opens below it as a full, labelled list. It closes when a page is
 * chosen, on Escape, and when the screen widens back to the desktop rail.
 */
export function MobileMenu() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLButtonElement>(null);
  const pathname = usePathname();

  useEffect(() => {
    const nav = ref.current?.closest("nav.side");
    if (!nav) return;
    if (open) nav.setAttribute("data-open", "");
    else nav.removeAttribute("data-open");
  }, [open]);

  useEffect(() => setOpen(false), [pathname]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    const wide = window.matchMedia("(min-width: 761px)");
    const onWide = () => wide.matches && setOpen(false);
    window.addEventListener("keydown", onKey);
    wide.addEventListener("change", onWide);
    return () => {
      window.removeEventListener("keydown", onKey);
      wide.removeEventListener("change", onWide);
    };
  }, [open]);

  return (
    <button
      ref={ref}
      type="button"
      className="side-menu-btn"
      aria-expanded={open}
      aria-label={open ? "Close menu" : "Open menu"}
      onClick={() => setOpen((o) => !o)}
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
        {open ? <path d="M6 6l12 12M18 6L6 18" /> : <path d="M4 7h16M4 12h16M4 17h16" />}
      </svg>
      <span>{open ? "Close" : "Menu"}</span>
    </button>
  );
}
