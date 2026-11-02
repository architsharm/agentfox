"use client";

import { useEffect, useRef, useState } from "react";
import { ago } from "@/components/kit";
import {
  ACTION,
  STATE_AFTER,
  isHalted,
  refusalText,
  stateLabel,
  type ControlAction,
} from "@/lib/product/agentStatus";
import s from "./AgentStatus.module.css";

/**
 * The agent's one status control: Pause / Stop / Resume, each through a short
 * dialog that says what it does, quotes what the agent receives, and asks why.
 *
 * The dialog is a native <dialog> opened with showModal() (as `product/Modal`
 * does): Escape closes it, focus moves into it, the page behind is inert. The form
 * posts to `/api/agents/{slug}/control`, which goes back to the page it came from.
 */

type Who = { slug: string; name: string; actor?: string | null };

export function ControlDialog({
  slug,
  name,
  actor,
  action,
  onClose,
}: Who & { action: ControlAction | null; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [reason, setReason] = useState("");
  const [returnTo, setReturnTo] = useState("");

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (action && !d.open) {
      setReason("");
      setReturnTo(window.location.pathname + window.location.search);
      d.showModal();
      d.querySelector<HTMLElement>("[data-autofocus]")?.focus();
    } else if (!action && d.open) d.close();
  }, [action]);

  const a = action ? ACTION[action] : null;
  const halting = action === "quarantine" || action === "kill";
  return (
    <dialog
      ref={ref}
      className="modal"
      aria-labelledby={`ctl-${slug}-title`}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === ref.current) ref.current?.close();
      }}
    >
      {a && action ? (
        <form action={`/api/agents/${encodeURIComponent(slug)}/control`} method="POST">
          <div className="modal-head">
            <span id={`ctl-${slug}-title`}>
              {a.title} {name}?
            </span>
            <button type="button" className="modal-close" onClick={() => ref.current?.close()} aria-label="Close">
              ×
            </button>
          </div>
          <div className="modal-body">
            <input type="hidden" name="action" value={action} />
            <input type="hidden" name="name" value={name} />
            <input type="hidden" name="return_to" value={returnTo} />
            <p className={s.does}>{a.does}</p>
            {halting ? (
              <p className={s.receives}>
                Your agent receives: <code>&quot;{refusalText(STATE_AFTER[action], reason.trim(), actor || "you")}&quot;</code>
              </p>
            ) : null}
            <div className={s.field}>
              <label htmlFor={`ctl-${slug}-reason`}>{halting ? "Reason" : "What was dealt with"} (optional)</label>
              <input
                id={`ctl-${slug}-reason`}
                className="k-input"
                name="reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                maxLength={500}
                data-autofocus={halting ? "" : undefined}
                placeholder={halting ? "Suspected prompt injection in ticket 42" : "Root cause fixed"}
              />
            </div>
            <div className={s.actions}>
              <button type="button" className="k-btn" onClick={() => ref.current?.close()}>
                Cancel
              </button>
              <button type="submit" className={halting ? "k-btn-danger" : "k-btn-primary"} data-autofocus={halting ? undefined : ""}>
                {a.confirm}
              </button>
            </div>
          </div>
        </form>
      ) : null}
    </dialog>
  );
}

/** A button that opens the dialog for one action: the banner's Resume, Controls' "Pause…", the map panel's. */
export function ControlButton({
  slug,
  name,
  actor,
  action,
  label,
  className = "k-btn",
  disabled,
  title,
}: Who & { action: ControlAction; label?: string; className?: string; disabled?: boolean; title?: string }) {
  const [open, setOpen] = useState<ControlAction | null>(null);
  return (
    <>
      <button type="button" className={className} onClick={() => setOpen(action)} disabled={disabled} title={title}>
        {label || ACTION[action].verb}
      </button>
      <ControlDialog slug={slug} name={name} actor={actor} action={open} onClose={() => setOpen(null)} />
    </>
  );
}

/**
 * The header's control. Active: "Pause ▾", a menu of Pause (investigating) and Stop
 * (incident). Paused or stopped: "Resume".
 */
export function AgentStatusMenu({ slug, name, actor, state }: Who & { state: string }) {
  const [menu, setMenu] = useState(false);
  const [open, setOpen] = useState<ControlAction | null>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!menu) return;
    const away = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setMenu(false);
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMenu(false);
        button.current?.focus();
      }
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    wrap.current?.querySelector<HTMLButtonElement>("[role=menuitem]")?.focus();
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [menu]);

  const choose = (a: ControlAction) => {
    setMenu(false);
    setOpen(a);
  };
  const dialog = <ControlDialog slug={slug} name={name} actor={actor} action={open} onClose={() => setOpen(null)} />;

  if (isHalted(state)) {
    return (
      <>
        <button type="button" className="k-btn" onClick={() => setOpen("resume")} title={`${name} is ${stateLabel(state).toLowerCase()}: let its calls through again`}>
          Resume
        </button>
        {dialog}
      </>
    );
  }
  return (
    <div className={s.menuWrap} ref={wrap}>
      <button
        ref={button}
        type="button"
        className="k-btn"
        aria-haspopup="menu"
        aria-expanded={menu}
        onClick={() => setMenu((v) => !v)}
        title="Pause or stop this agent: every call is refused until you resume"
      >
        Pause ▾
      </button>
      {menu ? (
        <div className={s.menu} role="menu" aria-label={`Pause or stop ${name}`}>
          {(["quarantine", "kill"] as const).map((a) => (
            <button key={a} type="button" role="menuitem" className={s.item} onClick={() => choose(a)}>
              <span>{ACTION[a].verb}…</span>
              <small>{ACTION[a].intent === "incident" ? "Incident: same effect, recorded as an incident" : "Investigating: refuse calls while you look"}</small>
            </button>
          ))}
        </div>
      ) : null}
      {dialog}
    </div>
  );
}

/** On every agent tab while paused or stopped: who, when, why, and Resume. */
export function HaltedBanner({
  slug,
  name,
  actor,
  state,
  by,
  at,
  reason,
}: Who & { state: string; by?: string | null; at?: string | null; reason?: string | null }) {
  if (!isHalted(state)) return null;
  const label = stateLabel(state);
  return (
    <div className={s.banner} role="status">
      <span className={s.bannerText}>
        <span aria-hidden>{state === "killed" ? "⏹" : "⏸"} </span>
        <strong>
          {label} by {by || "someone"}
        </strong>
        {at ? <span suppressHydrationWarning> {ago(at)}</span> : ""}
        {reason ? (
          <>
            : <q>{reason}</q>
          </>
        ) : (
          ". No reason given."
        )}{" "}
        Every call from this agent is refused until you resume.
      </span>
      <ControlButton slug={slug} name={name} actor={actor} action="resume" />
    </div>
  );
}
