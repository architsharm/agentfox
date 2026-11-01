"use client";

/** Small client pieces for the landing pages: a copy chip, and scroll reveal. */

import { useEffect, useState } from "react";

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
