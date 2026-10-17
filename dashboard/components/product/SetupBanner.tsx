"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { projectHref } from "@/lib/product/project";
import { bannerFor, dismissKey, type Banner, type Onboarding, type ProjectSetup } from "@/lib/product/setupBanner";
import { useProjectScope } from "@/lib/product/useProjectScope";

/** Pages that are the setup themselves, or already show the checklist. */
const QUIET = ["/app/start", "/app/welcome"];

const POLL_MS = 4000;
const GIVE_UP_MS = 10 * 60_000;
const DISMISS_DAYS = 7;

function dismissed(key: string): boolean {
  try {
    const at = Number(window.localStorage.getItem(key) || 0);
    return Boolean(at) && Date.now() - at < DISMISS_DAYS * 86_400_000;
  } catch {
    return false;
  }
}

/**
 * One line at the top of every page saying what to do next, sized to the next
 * missing step and gone when there is none. In a project it is about that project
 * (proposed, no traffic, no tool permissions, only watching); otherwise about the
 * workspace (no agents, nothing received). While it waits for a first request it
 * polls, and clears itself the moment one arrives.
 */
export function SetupBanner({ onboarding, initialProject }: { onboarding: Onboarding | null; initialProject: string | null }) {
  const pathname = usePathname();
  const router = useRouter();
  const [scope] = useProjectScope(initialProject);
  const [workspace, setWorkspace] = useState(onboarding);
  const [project, setProject] = useState<ProjectSetup | null>(null);
  const [hidden, setHidden] = useState<Record<string, boolean>>({});

  useEffect(() => setWorkspace(onboarding), [onboarding]);

  // The project's own state, fetched when the scope changes and on each navigation.
  useEffect(() => {
    if (!scope) return setProject(null);
    let live = true;
    fetch(`/api/agents/${encodeURIComponent(scope)}/setup`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((body) => live && setProject(body))
      .catch(() => live && setProject(null));
    return () => {
      live = false;
    };
  }, [scope, pathname]);

  const banner = bannerFor(scope ? project : null, scope ? null : workspace);
  const shownKey = banner ? dismissKey(scope, banner.kind) : "";

  // Storage is read after mounting, so the server's render and the first client
  // render agree; a dismissed banner then goes away.
  useEffect(() => {
    if (shownKey && dismissed(shownKey)) setHidden((h) => ({ ...h, [shownKey]: true }));
  }, [shownKey]);
  const waiting = banner?.kind === "traffic" || banner?.kind === "first-request";

  // Waiting for a first request: ask until it arrives, then refresh the page under it.
  useEffect(() => {
    if (!waiting) return;
    const started = Date.now();
    const timer = setInterval(async () => {
      if (Date.now() - started > GIVE_UP_MS) return clearInterval(timer);
      if (document.hidden) return;
      try {
        if (scope) {
          const r = await fetch(`/api/agents/${encodeURIComponent(scope)}/setup`, { cache: "no-store" });
          const body = r.ok ? await r.json() : null;
          if (body && body.traces > 0) {
            setProject(body);
            router.refresh();
          }
        } else {
          const r = await fetch("/api/onboarding", { cache: "no-store" });
          const body = r.ok ? await r.json() : null;
          if (body?.connected) {
            setWorkspace(body);
            router.refresh();
          }
        }
      } catch {
        // Transient: the next tick tries again.
      }
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [waiting, scope, router]);

  if (!banner || QUIET.some((p) => pathname === p || pathname.startsWith(`${p}/`))) return null;
  // Home already carries the workspace checklist.
  if (!scope && pathname === "/app" && banner.kind === "next-step") return null;
  const key = dismissKey(scope, banner.kind);
  if (hidden[key] ?? false) return null;

  const hide = () => {
    try {
      window.localStorage.setItem(key, String(Date.now()));
    } catch {
      // Without storage it hides for this page view only.
    }
    setHidden({ ...hidden, [key]: true });
  };

  return (
    <div className={`setup-banner setup-${banner.tone}`} role="region" aria-label="Setup">
      <div className="setup-main">
        <strong>{banner.title}</strong>
        <span>{banner.body}</span>
        {banner.snippet && <Snippet text={banner.snippet} />}
        {waiting && (
          <span className="setup-waiting">
            <i aria-hidden /> Waiting for the first request. This clears by itself.
          </span>
        )}
      </div>
      <div className="setup-actions">
        {banner.kind === "enforce" && scope ? <Enforce slug={scope} /> : null}
        {banner.kind === "add" && project ? <AddProject id={project.id} /> : null}
        {banner.actions.map((a, i) => (
          <Link key={a.href} href={a.href} className={i === 0 && banner.kind !== "enforce" && banner.kind !== "add" ? "k-btn-primary" : "k-btn"}>
            {a.label}
          </Link>
        ))}
        <button type="button" className="setup-close" aria-label="Hide for a week" title="Hide for a week" onClick={hide}>
          ×
        </button>
      </div>
    </div>
  );
}

function Snippet({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="setup-snippet">
      <pre>{text}</pre>
      <button
        type="button"
        className="k-btn"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(text);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          } catch {
            // Clipboard refused: the text is selectable.
          }
        }}
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

/** Add a proposed project, staying on its page. */
function AddProject({ id }: { id: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  return (
    <button
      type="button"
      className="k-btn-primary"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        await fetch(`/api/agents/${encodeURIComponent(id)}/approve`, { method: "POST" }).catch(() => null);
        setBusy(false);
        router.refresh();
      }}
    >
      Add project
    </button>
  );
}

/** Two steps: what blocking would have stopped last week, then switch it on. */
function Enforce({ slug }: { slug: string }) {
  const router = useRouter();
  const [preview, setPreview] = useState<{ would_stop: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const base = `/api/agents/${encodeURIComponent(slug)}/enforcement`;
  if (!preview)
    return (
      <button
        type="button"
        className="k-btn-primary"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          const r = await fetch(`${base}/preview`, { method: "POST" }).catch(() => null);
          setBusy(false);
          if (!r?.ok) return setError("Could not check the last week.");
          setPreview(await r.json());
        }}
      >
        {busy ? "Checking…" : error || "What would it block?"}
      </button>
    );
  return (
    <>
      <span className="setup-preview">
        Last 7 days: would have stopped {preview.would_stop} request{preview.would_stop === 1 ? "" : "s"}.
      </span>
      <button
        type="button"
        className="k-btn-primary"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          const r = await fetch(base, { method: "POST" }).catch(() => null);
          setBusy(false);
          if (!r?.ok) return setError("Could not turn blocking on. It needs a role that may enforce policies.");
          router.refresh();
          window.location.reload();
        }}
      >
        Turn blocking on
      </button>
      {error && <span className="k-act-error">{error}</span>}
      <Link className="k-btn" href={projectHref(slug)}>
        Review on canvas
      </Link>
    </>
  );
}

export type { Banner };
