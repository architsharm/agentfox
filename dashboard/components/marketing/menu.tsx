"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import type { NavGroup } from "@/lib/marketing/nav";

/**
 * The header dropdown.
 *
 * Why a client component and not a `<details>` or a CSS `:hover` menu. A
 * pointer-only menu is unusable from a keyboard, and a `<details>` opens on
 * click and stays open when you move to the next one, which reads as broken
 * on a nav bar. The behaviour people expect here is genuinely stateful:
 * opens on hover *and* on focus, the whole group is one tab stop away from
 * its links, Escape closes and returns focus to the button, and clicking
 * outside closes.
 *
 * `aria-expanded` and `aria-controls` on the button, and the panel is a plain
 * list, so a screen reader gets a disclosure rather than a mystery.
 *
 * Each item renders its `note` under the label. That is the point of the
 * whole thing: the reference site this answers to puts a sentence under every
 * menu item, and it means a visitor learns what the product is made of
 * without opening anything. A menu of bare labels makes them guess.
 */
export function NavMenu({ group }: { group: NavGroup }) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const closeTimer = useRef<number | null>(null);
  /**
   * Which input opened this, because two of them must not both act.
   *
   * With hover-to-open, a plain toggle on click closes the menu the pointer
   * is already inside: move onto "Resources", it opens, click it, it shuts.
   * That reads as broken, and it is what every hover menu gets wrong once.
   *
   * So a mouse click is a no-op — hover already owns the open. A touch has no
   * hover to own it, and keyboard activation fires `click` with no pointer
   * event before it, so both of those still toggle.
   */
  const lastPointer = useRef<string>("");
  const id = `dd-${group.label.toLowerCase().replace(/\W+/g, "-")}`;

  // A small delay on leaving, so the diagonal path from the button to the
  // far side of the panel does not close it out from under the pointer.
  const openNow = () => {
    if (closeTimer.current) window.clearTimeout(closeTimer.current);
    setOpen(true);
  };
  const closeSoon = () => {
    if (closeTimer.current) window.clearTimeout(closeTimer.current);
    closeTimer.current = window.setTimeout(() => setOpen(false), 140);
  };

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      button.current?.focus();
    };
    const onDown = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, [open]);

  useEffect(() => () => {
    if (closeTimer.current) window.clearTimeout(closeTimer.current);
  }, []);

  return (
    <div
      className="mk-dd"
      ref={wrap}
      onMouseEnter={openNow}
      onMouseLeave={closeSoon}
      // Focus anywhere inside opens it; focus leaving the whole group closes
      // it. This is what makes tabbing through the header work.
      onFocus={openNow}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node)) setOpen(false);
      }}
    >
      <button
        ref={button}
        type="button"
        className="mk-dd-button"
        aria-expanded={open}
        aria-controls={id}
        onPointerDown={(e) => {
          lastPointer.current = e.pointerType;
        }}
        onClick={() => {
          if (lastPointer.current === "mouse") {
            lastPointer.current = "";
            return;
          }
          setOpen((v) => !v);
        }}
      >
        {group.label}
        <svg width="10" height="6" viewBox="0 0 10 6" aria-hidden focusable="false">
          <path
            d="M1 1l4 4 4-4"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </svg>
      </button>

      <div id={id} className="mk-dd-panel" data-open={open || undefined} hidden={!open}>
        {/* Two real columns, not a grid of sections that happens to wrap.
            Sections declare which column they belong to, so the long group
            sits beside the two short ones instead of dragging the panel down
            to the height of the longest list. */}
        <div className="mk-dd-inner">
          {[1, 2].map((col) => {
            const sections = group.sections.filter((s) => (s.column ?? 1) === col);
            if (sections.length === 0) return null;
            return (
              <div key={col} className="mk-dd-col">
                {sections.map((section) => (
                  <div key={section.heading} className="mk-dd-section">
                    <p className="mk-dd-heading">{section.heading}</p>
                    <ul>
                      {section.items.map((item) => (
                        <li key={item.href}>
                          <Link href={item.href} onClick={() => setOpen(false)}>
                            <b>{item.label}</b>
                            <span>{item.note}</span>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
