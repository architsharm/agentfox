"use client";

/** Small client pieces for the landing pages: a copy chip, and scroll reveal. */

import { useEffect, useRef, useState } from "react";

export function CopyChip({ text, wide = false }: { text: string; wide?: boolean }) {
  const [done, setDone] = useState(false);
  return (
    <span className={`lp-copy${wide ? " is-wide" : ""}`}>
      <code>{text}</code>
      <button
        type="button"
        aria-label={`Copy ${text}`}
        onClick={() => {
          navigator.clipboard?.writeText(text).then(
            () => {
              setDone(true);
              setTimeout(() => setDone(false), 1400);
            },
            () => {},
          );
        }}
      >
        {done ? (
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden>
            <path d="M3 8.5 6.5 12 13 4.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        ) : (
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden>
            <rect x="5.5" y="5.5" width="8" height="8" rx="1.5" />
            <path d="M10.5 3.5v-.5A1.5 1.5 0 0 0 9 1.5H3A1.5 1.5 0 0 0 1.5 3v6A1.5 1.5 0 0 0 3 10.5h.5" />
          </svg>
        )}
      </button>
    </span>
  );
}

/**
 * Fades elements marked `data-reveal` up into place as they scroll in. Content is
 * visible without JavaScript: the hiding class is only added once this runs.
 */
export function Reveal() {
  useEffect(() => {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const root = document.documentElement;
    root.classList.add("lp-reveal-on");
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            e.target.classList.add("is-in");
            io.unobserve(e.target);
          }
        }
      },
      { rootMargin: "0px 0px -4% 0px", threshold: 0.01 },
    );
    document.querySelectorAll("[data-reveal]").forEach((el) => io.observe(el));
    return () => {
      io.disconnect();
      root.classList.remove("lp-reveal-on");
    };
  }, []);
  return null;
}

/**
 * One button that flips between light and dark. Same storage key and attribute as
 * the app's ThemeToggle, so the choice carries over after signing in.
 */
export function ThemeButton() {
  function flip() {
    const root = document.documentElement;
    const dark =
      root.getAttribute("data-theme") === "dark" ||
      (!root.hasAttribute("data-theme") && window.matchMedia("(prefers-color-scheme: dark)").matches);
    const next = dark ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try {
      localStorage.setItem("agentfox-theme", next);
    } catch {
      // Private mode: the switch still applies to this page.
    }
  }
  return (
    <button type="button" className="lp-iconbtn lp-theme" onClick={flip} aria-label="Switch theme" title="Switch theme">
      <svg className="lp-theme-moon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
      </svg>
      <svg className="lp-theme-sun" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden>
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4" />
      </svg>
    </button>
  );
}

/**
 * Closes the header's mobile menu (a plain <details>, so Enter and Space open and
 * close it with no script at all) on Escape, handing focus back to its button, and
 * on a click outside it. Rendered inside the <details> it controls.
 */
export function MenuDismiss() {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const menu = ref.current?.closest("details");
    if (!menu) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || !menu.open) return;
      menu.open = false;
      menu.querySelector("summary")?.focus();
    };
    const onPointer = (e: PointerEvent) => {
      if (menu.open && !menu.contains(e.target as Node)) menu.open = false;
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, []);
  return <span ref={ref} hidden />;
}
