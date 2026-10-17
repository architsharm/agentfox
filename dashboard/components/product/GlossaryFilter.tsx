"use client";

/*
 * Finding one term in the Glossary.
 *
 * The page is 31 definitions across six tables and roughly 1,700 words, and a
 * reader arrives at it with exactly one question: what does *this* word mean.
 * There was no index, no anchors and no search, so answering that question meant
 * reading a reference document top to bottom, or ctrl-F — which is the reader
 * building the feature themselves.
 *
 * Why this filters the DOM instead of owning the rows:
 *
 * The definitions are prose with links and inline code in them. Lifting them out
 * of the server component into a data array to render them here would turn 300
 * lines of readable JSX into 300 lines of escaped strings or ReactNode props, and
 * would move a page with no client JS at all onto the client. The rows are static
 * server output — nothing in React will ever re-render them — so toggling their
 * `hidden` attribute from outside is safe in a way it would not be for live data.
 *
 * It degrades to exactly the page that exists today: the input renders only after
 * hydration (so it is never a dead control someone types into and watches do
 * nothing), and with JS off every row stays visible, which is the whole glossary.
 */

import { useEffect, useRef, useState } from "react";

export function GlossaryFilter({ total }: { total: number }) {
  const [ready, setReady] = useState(false);
  const [q, setQ] = useState("");
  const [shown, setShown] = useState(total);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => setReady(true), []);

  useEffect(() => {
    if (!ready) return;
    const needle = q.trim().toLowerCase();
    // Two kinds of searchable item. Most are table rows, but OWASP and MITRE
    // ATLAS are explained in a paragraph rather than a table, and a search for
    // "atlas" has to be able to return them — so those sections carry
    // `data-term` themselves and are filtered as single items.
    const rows = [...document.querySelectorAll<HTMLElement>("[data-term]")];

    // Two passes, and the order matters. Matching term names alone fails the
    // commonest case — you half-remember the idea, not the label, so "taint"
    // should find "Argument provenance". But matching definition text as well,
    // in one pass, means "policy" returns two thirds of the glossary, because
    // half these definitions mention policies.
    //
    // So: if any TERM matches, those are the answer. Only when none does do we
    // fall back to searching the definitions. Typing a word that is a term gets
    // you that term; typing a word that is merely discussed gets you every place
    // it is discussed.
    const byTerm = needle ? rows.filter((r) => (r.dataset.term || "").includes(needle)) : rows;
    const hits = new Set(
      byTerm.length > 0 ? byTerm : rows.filter((r) => (r.textContent || "").toLowerCase().includes(needle)),
    );

    let visible = 0;
    for (const row of rows) {
      const hit = !needle || hits.has(row);
      row.hidden = !hit;
      if (hit) visible++;
    }

    // A section heading over a table with every row hidden is a heading over
    // nothing, so sections fold away with their contents. A section that IS an
    // item (the prose-only ones) has already had `hidden` set by the loop above
    // and must not be reconsidered here — it contains no rows, so asking
    // whether any of its rows survived would hide it every time.
    for (const sec of document.querySelectorAll<HTMLElement>("[data-gl-section]")) {
      if (sec.hasAttribute("data-term")) continue;
      sec.hidden = !sec.querySelector("[data-term]:not([hidden])");
    }

    setShown(visible);
  }, [q, ready]);

  // The page renders fine without this; it just renders without a search box.
  if (!ready) return null;

  return (
    <div className="gl-find">
      <label className="gl-find-box">
        <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden focusable="false">
          <circle cx="7" cy="7" r="4.6" fill="none" stroke="currentColor" strokeWidth="1.6" />
          <path d="M10.4 10.4 14 14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
        <input
          id="glossary-find"
          ref={input}
          type="search"
          value={q}
          placeholder={`Find a term — ${total} defined`}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") setQ("");
          }}
          aria-label="Filter glossary terms"
          aria-describedby="glossary-find-count"
        />
        {q && (
          <button type="button" className="gl-find-clear" onClick={() => { setQ(""); input.current?.focus(); }}>
            Clear
          </button>
        )}
      </label>
      {/* aria-live so a screen reader hears the result count change; the count is
          only rendered while filtering, because "31 of 31" is not information. */}
      <p className="gl-find-count" id="glossary-find-count" aria-live="polite">
        {q && (shown === 0 ? `No term matches “${q.trim()}”.` : `${shown} of ${total}`)}
      </p>
    </div>
  );
}
