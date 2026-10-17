"use client";

import { useState } from "react";

/**
 * A small "ⓘ" badge that actually shows its explanation. This used to rely
 * solely on the native `title=` attribute, which only appears on a genuine
 * mouse hover after a ~1s delay, never on click or keyboard focus in most
 * browsers — so clicking or tapping it did nothing, which is exactly the bug
 * a UX pass caught. Now it opens a real, visible popover on click, hover, or
 * keyboard focus, and closes on a second click or blur. Kept in its own file
 * (rather than "use client" at the top of ui.tsx) so the plain helper
 * functions there — ts(), pct(), etc. — stay callable directly from server
 * components instead of being forced into the client bundle too.
 */
export function InfoTip({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <span
      className="info-tip"
      aria-label={text}
      tabIndex={0}
      onClick={(e) => {
        e.stopPropagation();
        setOpen((o) => !o);
      }}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      i
      {open && (
        <span className="info-tip-bubble" role="tooltip">
          {text}
        </span>
      )}
    </span>
  );
}
