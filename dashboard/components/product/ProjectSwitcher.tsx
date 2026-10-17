"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { projectHref } from "@/lib/product/project";

export type ProjectOption = { slug: string; name: string; status?: string };

/**
 * The scope picker at the top of the sidebar, as in Figma's file switcher: the
 * project you are in, and a menu of the others plus All projects. Choosing one
 * opens it; choosing All projects opens the workspace's Home.
 */
export function ProjectSwitcher({
  projects,
  current,
  onChoose,
}: {
  projects: ProjectOption[];
  current: string | null;
  onChoose: (slug: string | null) => void;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
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

  const here = projects.find((p) => p.slug === current);
  const label = current ? here?.name || current : "All projects";
  const shown = filter
    ? projects.filter((p) => `${p.name} ${p.slug}`.toLowerCase().includes(filter.toLowerCase()))
    : projects;

  const go = (slug: string | null) => {
    setOpen(false);
    setFilter("");
    onChoose(slug);
    router.push(slug ? projectHref(slug) : "/app");
  };

  return (
    <div className="project-switch" ref={box}>
      <button type="button" className="project-switch-btn" aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="project-switch-dot" data-all={current ? undefined : ""} aria-hidden="true">
          {current ? (label[0] || "?").toUpperCase() : "∗"}
        </span>
        <span className="project-switch-name">
          <small>{current ? "Project" : "Scope"}</small>
          {label}
        </span>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="m7 9 5-5 5 5M7 15l5 5 5-5" />
        </svg>
      </button>
      {open && (
        <div className="project-switch-menu" role="listbox" aria-label="Projects">
          {projects.length > 7 && (
            <input autoFocus className="project-switch-filter" placeholder="Find a project" value={filter} onChange={(e) => setFilter(e.target.value)} />
          )}
          <button type="button" role="option" aria-selected={!current} className={!current ? "on" : undefined} onClick={() => go(null)}>
            <span className="project-switch-dot" data-all="" aria-hidden="true">∗</span>
            All projects
          </button>
          {shown.length > 0 && <div className="project-switch-sep" />}
          <div className="project-switch-list">
            {shown.map((p) => (
              <button type="button" role="option" key={p.slug} aria-selected={p.slug === current} className={p.slug === current ? "on" : undefined} onClick={() => go(p.slug)}>
                <span className="project-switch-dot" aria-hidden="true">{(p.name[0] || "?").toUpperCase()}</span>
                <span className="project-switch-opt">{p.name}</span>
                {p.status === "paused" && <small>paused</small>}
                {p.status === "draft" && <small>proposed</small>}
              </button>
            ))}
          </div>
          <div className="project-switch-sep" />
          <Link href="/app/projects" onClick={() => { setOpen(false); onChoose(null); }} className="project-switch-foot">Manage projects</Link>
          <Link href="/app/start" onClick={() => setOpen(false)} className="project-switch-foot">Add a project</Link>
        </div>
      )}
    </div>
  );
}
