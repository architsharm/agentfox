"use client";

import { useRef, type ReactNode } from "react";

/**
 * A native <dialog> gives us focus trapping, Esc-to-close and a real backdrop for
 * free — no portal library, no manual focus management. The only thing it doesn't
 * do on its own is close on a backdrop click, which the onClick check below adds
 * (comparing the click target to the dialog element itself, since a click inside
 * the panel bubbles up to the dialog too but with a different target).
 */
export function Modal({
  trigger,
  triggerClassName = "btn-scan",
  title,
  children,
}: {
  trigger: ReactNode;
  triggerClassName?: string;
  title: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  return (
    <>
      <button type="button" className={triggerClassName} onClick={() => ref.current?.showModal()}>
        {trigger}
      </button>
      <dialog
        ref={ref}
        className="modal"
        onClick={(e) => {
          if (e.target === ref.current) ref.current?.close();
        }}
      >
        <div className="modal-head">
          <span>{title}</span>
          <button type="button" className="modal-close" onClick={() => ref.current?.close()} aria-label="Close">
            ×
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </dialog>
    </>
  );
}
