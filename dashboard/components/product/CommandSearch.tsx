"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

type NavItem = { label: string; href: string; group: string };

/**
 * The shell had no way to jump straight to a page or a specific record — only
 * sequential nav clicks. Full entity search would need a backend endpoint this
 * pass doesn't add; what this does instead: fuzzy-match nav pages by name, and
 * recognise the ID prefixes the product already hands out everywhere it links to a
 * trace or finding (trc_..., fnd_...) so pasting one jumps straight there.
 */
export function CommandSearch({ nav }: { nav: NavItem[] }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (open) {
      setQ("");
      setActive(0);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  const results = useMemo(() => {
    const trimmed = q.trim();
    const jump = /^(trc_|fnd_)[a-zA-Z0-9]+$/.test(trimmed)
      ? [
          {
            label: `Jump to ${trimmed}`,
            href: trimmed.startsWith("trc_") ? `/app/traces/${trimmed}` : `/app/findings/${trimmed}`,
            group: "Jump to ID",
          },
        ]
      : [];
    if (!trimmed) return [...jump, ...nav];
    const needle = trimmed.toLowerCase();
    const matched = nav.filter(
      (item) => item.label.toLowerCase().includes(needle) || item.group.toLowerCase().includes(needle),
    );
    return [...jump, ...matched];
  }, [q, nav]);

  function go(href: string) {
    setOpen(false);
    router.push(href);
  }

  if (!open) {
    return (
      <button type="button" className="cmdk-trigger" onClick={() => setOpen(true)}>
        <SearchIcon />
        <span>Search</span>
        <span className="cmdk-kbd">⌘K</span>
      </button>
    );
  }

  return (
    <div className="cmdk-overlay" onClick={() => setOpen(false)}>
      <div className="cmdk-panel" onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setActive(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((a) => Math.min(a + 1, results.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => Math.max(a - 1, 0));
            } else if (e.key === "Enter" && results[active]) {
              go(results[active].href);
            }
          }}
          placeholder="Search pages, or paste a trace/finding id (trc_.../fnd_...)"
          className="cmdk-input"
        />
        <div className="cmdk-list">
          {results.length === 0 && <div className="cmdk-empty small muted">No matches.</div>}
          {results.map((item, i) => (
            <button
              type="button"
              key={item.href + item.label}
              className={`cmdk-item${i === active ? " active" : ""}`}
              onMouseEnter={() => setActive(i)}
              onClick={() => go(item.href)}
            >
              <span className="small">{item.label}</span>
              <span className="small muted">{item.group}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function SearchIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2" />
      <path d="m20 20-3.5-3.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
