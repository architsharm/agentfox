"use client";

import { useState, type ReactNode } from "react";

/**
 * One way in, on Settings > Connections: what it is, whether it is live, and one
 * thing to do. A card whose action is "show me how" opens in place, across the
 * full row so a snippet or form has room, instead of navigating away.
 */
export function ConnCard({
  title,
  status,
  text,
  action,
  expandLabel,
  children,
  id,
}: {
  title: string;
  status: ReactNode;
  text: string;
  /** The one primary action. Ignored when `expandLabel` is set. */
  action?: ReactNode;
  /** Label of the button that opens `children` in place. */
  expandLabel?: string;
  children?: ReactNode;
  id?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <section id={id} className={`k-card conn-card${open ? " open" : ""}`}>
      <div className="conn-head">
        <h3>{title}</h3>
        {status}
      </div>
      <p className="conn-text">{text}</p>
      <div className="conn-foot">
        {expandLabel ? (
          <button type="button" className={open ? "k-btn-ghost" : "k-btn-primary"} aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? "Close" : expandLabel}
          </button>
        ) : (
          action
        )}
      </div>
      {expandLabel && open && <div className="conn-more">{children}</div>}
    </section>
  );
}
