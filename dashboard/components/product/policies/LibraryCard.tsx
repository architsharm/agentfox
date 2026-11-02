"use client";

import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode, type SyntheticEvent } from "react";
import { useSearchParams } from "next/navigation";
import { Act } from "@/components/kit/Act";

/** Clicks and keys on a card's own buttons (and their confirm prompts) stay theirs. */
const keep = (e: SyntheticEvent) => e.stopPropagation();

/**
 * A library card that opens the library's drawer when clicked anywhere but its
 * buttons. The drawer is a native <dialog>, as in Modal: focus trapping, Escape and
 * a backdrop for free, and a click on the backdrop closes it. It sits beside the
 * card, not inside it, so clicks within it never reach the card.
 *
 * `?open=<library id>` opens it on arrival: a library's own URL lands here.
 */
export function LibraryCard({
  id,
  title,
  className = "",
  head,
  state,
  actions,
  drawer,
}: {
  id: string;
  title: string;
  className?: string;
  head: ReactNode;
  state: ReactNode;
  actions: ReactNode;
  drawer: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const params = useSearchParams();
  const open = () => {
    if (ref.current && !ref.current.open) ref.current.showModal();
  };
  const close = () => {
    ref.current?.close();
  };
  useEffect(() => {
    if (params.get("open") === id) open();
    // Only on arrival: closing must not reopen it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const onKey = (e: KeyboardEvent) => {
    if (e.target !== e.currentTarget || (e.key !== "Enter" && e.key !== " ")) return;
    e.preventDefault();
    open();
  };

  return (
    <>
      <article
        className={`lib-card lib-open ${className}`}
        role="button"
        tabIndex={0}
        aria-haspopup="dialog"
        aria-label={`${title}: see its rules`}
        onClick={open}
        onKeyDown={onKey}
      >
        {head}
        <div className="lib-foot">
          {state}
          <span className="lib-actions" onClick={keep} onKeyDown={keep}>
            {actions}
          </span>
        </div>
      </article>
      <dialog
        ref={ref}
        className="modal lib-drawer"
        aria-label={title}
        onClick={(e) => {
          if (e.target === ref.current) close();
        }}
        onClose={() => {
          // Leave the URL as the page, so a reload doesn't reopen what was closed.
          if (params.get("open") === id) {
            const url = new URL(window.location.href);
            url.searchParams.delete("open");
            window.history.replaceState(null, "", url);
          }
        }}
      >
        <div className="modal-head">
          <span>{title}</span>
          <button type="button" className="modal-close" onClick={close} aria-label="Close">
            ×
          </button>
        </div>
        <div className="modal-body">{drawer}</div>
      </dialog>
    </>
  );
}

type ApplyTo = { url: string; body?: unknown; label: string; confirm?: string };

/**
 * Apply, with one scope model everywhere: the chosen project's agents by default, and
 * every agent as the explicit second choice, behind ▾.
 */
export function ApplyChoice({ project, every }: { project: ApplyTo; every: ApplyTo }) {
  const [more, setMore] = useState(false);
  return (
    <span className="lib-apply">
      <Act url={project.url} body={project.body} className="k-btn-primary" done="Applied" confirm={project.confirm}>
        {project.label}
      </Act>
      <button type="button" className="k-btn lib-apply-more" aria-expanded={more} aria-label="More ways to apply" onClick={() => setMore((m) => !m)}>
        ▾
      </button>
      {more && (
        <span className="lib-apply-menu">
          <Act url={every.url} body={every.body} className="k-btn" done="Applied" confirm={every.confirm}>
            {every.label}
          </Act>
        </span>
      )}
    </span>
  );
}
