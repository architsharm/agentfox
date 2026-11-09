"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { useRouter } from "next/navigation";
import { MAP_PROJECT_COOKIE, NEW_PROJECT, PROJECT_COOKIE_AGE, defaultProject, disconnectedBy, type ProjectRow } from "@/lib/product/project";

/** A project: one repository `agentfox init` mapped (or a system no repository holds), and how many agents its map draws. */
export type ProjectOption = ProjectRow;

/** What a person calls a project: its repository when it came from one, else the root
 *  agent's name. `project` stays the key every route takes. */
export function projectLabel(p: ProjectOption): string {
  if (p.repo) return p.repo;
  if (p.repos?.length === 1) return p.repos[0];
  return p.name || p.project;
}

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
  const btn = useRef<HTMLButtonElement>(null);
  // The sidebar scrolls, so anything positioned inside it is clipped to its 224px
  // ("1 a", "All projects and age…"). The menu is fixed to the viewport instead, at
  // the button, and may be wider than the sidebar.
  const [at, setAt] = useState<CSSProperties>({});
  const toggle = () => {
    const r = btn.current?.getBoundingClientRect();
    if (r) setAt({ "--psm-top": `${r.bottom + 4}px`, "--psm-left": `${r.left}px`, "--psm-min": `${r.width}px` } as CSSProperties);
    setOpen(!open);
  };

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    // A fixed menu would stay put while the button scrolled away under it.
    const moved = (e: Event) => !(e.target instanceof Node && box.current?.contains(e.target)) && setOpen(false);
    const resized = () => setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    document.addEventListener("scroll", moved, true);
    window.addEventListener("resize", resized);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
      document.removeEventListener("scroll", moved, true);
      window.removeEventListener("resize", resized);
    };
  }, [open]);

  const adding = current === NEW_PROJECT;
  const here = adding ? undefined : (projects.find((p) => p.project === current) ?? defaultProject(projects));
  const agents = (n: number) => (n === 1 ? "1 agent" : `${n} agents`);

  const go = (project: string) => {
    setOpen(false);
    document.cookie = `${MAP_PROJECT_COOKIE}=${encodeURIComponent(project)}; path=/; max-age=${PROJECT_COOKIE_AGE}; samesite=lax`;
    router.push(project === NEW_PROJECT ? "/app/map" : `/app/map?project=${encodeURIComponent(project)}`);
    router.refresh();
  };

  // Disconnect: exactly the agents the dialog names leave the dashboard; `agentfox init` proposes them again.
  const leaving = here ? disconnectedBy(here) : [];
  const staying = here ? (here.members ?? []).filter((m) => !leaving.some((l) => l.slug === m.slug) && !["removed", "rejected"].includes(m.status ?? "")) : [];
  const names = (list: { slug: string; name?: string }[]) => {
    const all = list.map((m) => m.name || m.slug);
    return all.length > 5 ? `${all.slice(0, 5).join(", ")} and ${all.length - 5} more` : all.join(", ");
  };
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
      <button ref={btn} type="button" className="project-switch-btn" aria-haspopup="listbox" aria-expanded={open} onClick={toggle}>
        <span className="project-switch-name">
          <small>{adding ? "not connected yet" : here ? agents(here.agents) : "no project yet"}</small>
          {adding ? "New project" : here ? projectLabel(here) : "Set up a project"}
        </span>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="m7 9 5-5 5 5M7 15l5 5 5-5" />
        </svg>
      </button>
      {open && (
        <div className="project-switch-menu" role="listbox" aria-label="Projects" style={at}>
          {/* Every project and agent, with the ones a later `agentfox init` proposed
              waiting to be added. First, because it is the way out of one project. */}
          <Link href="/app/projects" className="project-switch-foot project-switch-all" onClick={() => setOpen(false)}>
            All projects
          </Link>
          {projects.length > 0 && <div className="project-switch-sep" />}
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
                <span className="project-switch-opt">{projectLabel(p)}</span>
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
              Disconnect {projectLabel(here)}…
            </button>
          )}
          {here && confirming && (
            <div className="project-switch-confirm" role="alertdialog" aria-label={`Disconnect ${projectLabel(here)}`}>
              <p>
                <b>Disconnect {projectLabel(here)}?</b>{" "}
                {leaving.length === 1 ? "This agent leaves" : `These ${leaving.length} agents leave`} Agents and the map: {names(leaving)}.{" "}
                {leaving.length === 1 ? "Its" : "Their"} guardrails are emptied (and kept, to put back later) and {leaving.length === 1 ? "its" : "their"} tool
                permissions revoked. Past traffic and issues are kept.
                {staying.length > 0 && ` ${names(staying)} ${staying.length === 1 ? "is" : "are"} from another repository and ${staying.length === 1 ? "stays" : "stay"}.`}{" "}
                Run <code>agentfox init</code> in the repository again to propose {leaving.length === 1 ? "it" : "them"} again.
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
