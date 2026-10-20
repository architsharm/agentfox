"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { MAP_PROJECT_COOKIE, NEW_PROJECT, PROJECT_COOKIE_AGE } from "@/lib/product/project";

/** A project: one repository `agentfox init` mapped, and how many agents are in it. */
export type ProjectOption = { project: string; agents: number };

/**
 * The project at the top of the sidebar. The dashboard is always in exactly one:
 * the Map draws that project's agents and nothing from any other. Choosing another
 * opens its map.
 */
export function ProjectSwitcher({ projects, current }: { projects: ProjectOption[]; current: string | null }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  const adding = current === NEW_PROJECT;
  const here = adding ? undefined : (projects.find((p) => p.project === current) ?? projects[0]);
  const agents = (n: number) => (n === 1 ? "1 agent" : `${n} agents`);

  const go = (project: string) => {
    setOpen(false);
    document.cookie = `${MAP_PROJECT_COOKIE}=${encodeURIComponent(project)}; path=/; max-age=${PROJECT_COOKIE_AGE}; samesite=lax`;
    router.push(project === NEW_PROJECT ? "/app/map" : `/app/map?project=${encodeURIComponent(project)}`);
    router.refresh();
  };

  // Disconnect: its agents leave the dashboard; `agentfox init` brings it back as new.
  const disconnect = async () => {
    if (!here) return;
    setBusy(true);
    setError("");
    const res = await fetch(`/api/projects/${encodeURIComponent(here.project)}`, { method: "DELETE" }).catch(() => null);
    setBusy(false);
    if (!res?.ok) {
      const body = await res?.json().catch(() => ({}));
      setError(body?.detail || "Couldn't disconnect it. Try again.");
      return;
    }
    setConfirming(false);
    const next = projects.find((p) => p.project !== here.project);
    go(next ? next.project : NEW_PROJECT);
  };

  return (
    <div className="project-switch" ref={box}>
      <button type="button" className="project-switch-btn" aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="project-switch-name">
          <small>{adding ? "not connected yet" : here ? agents(here.agents) : "no project yet"}</small>
          {adding ? "New project" : (here?.project ?? "Set up a project")}
        </span>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="m7 9 5-5 5 5M7 15l5 5 5-5" />
        </svg>
      </button>
      {open && (
        <div className="project-switch-menu" role="listbox" aria-label="Projects">
          <div className="project-switch-list">
            {projects.map((p) => (
              <button
                type="button"
                role="option"
                key={p.project}
                aria-selected={p.project === here?.project}
                className={p.project === here?.project ? "on" : undefined}
                onClick={() => go(p.project)}
              >
                <span className="project-switch-opt">{p.project}</span>
                <small>{agents(p.agents)}</small>
              </button>
            ))}
          </div>
          {projects.length > 0 && <div className="project-switch-sep" />}
          <button type="button" onClick={() => go(NEW_PROJECT)} className="project-switch-foot">
            + Add a project
          </button>
          {here && !confirming && (
            <button type="button" onClick={() => setConfirming(true)} className="project-switch-foot project-switch-danger">
              Disconnect {here.project}…
            </button>
          )}
          {here && confirming && (
            <div className="project-switch-confirm" role="alertdialog" aria-label={`Disconnect ${here.project}`}>
              <p>
                <b>Disconnect {here.project}?</b> Its {agents(here.agents)} leave the dashboard and lose their guardrails and tool
                permissions. Past traffic and issues are kept. Run <code>agentfox init</code> again to bring it back as new.
              </p>
              {error && <p className="project-switch-error" role="alert">{error}</p>}
              <div>
                <button type="button" className="btn-reject" disabled={busy} onClick={disconnect}>
                  {busy ? "Disconnecting…" : "Disconnect"}
                </button>
                <button type="button" className="btn-scan" disabled={busy} onClick={() => setConfirming(false)}>
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
