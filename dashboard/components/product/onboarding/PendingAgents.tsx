"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { addLabel, pendingPrompt, type Arrival } from "@/lib/product/onboarding/connect";
import { MAP_PROJECT_COOKIE, PROJECT_COOKIE_AGE, projectHref } from "@/lib/product/project";

const DISMISSED = "agentfox.pending.dismissed";
const POLL_MS = 4000;

function readDismissed(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(DISMISSED) || "[]");
    return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

/**
 * "agentfox init found these agents: add them", on every page, for as long as they
 * wait. The setup card asks once, while it is open; this keeps asking after the card
 * has gone (the dashboard moves on to the project once init reports in), and asks for
 * a second repository's init, which no card is open for. It also refreshes the page
 * when a new init reports in, so the sidebar and the page show the new project live.
 *
 * `hidden`: the setup card is on screen and asks itself.
 */
export function PendingAgents({ hidden = false }: { hidden?: boolean }) {
  const router = useRouter();
  const [live, setLive] = useState<Arrival | null>(null);
  const [dismissed, setDismissed] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const seen = useRef<string | null | undefined>(undefined);
  // While the setup card is up it follows init itself; a refresh would pull it away.
  const quiet = useRef(hidden);
  quiet.current = hidden;

  useEffect(() => setDismissed(readDismissed()), []);

  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      if (stop) return;
      if (document.visibilityState === "visible") {
        try {
          const r = await fetch("/api/onboarding/structure", { cache: "no-store" });
          if (r.ok) {
            const body = (await r.json()) as Arrival;
            if (stop) return;
            setLive(body);
            const at = body.connectedAt ?? null;
            // A report newer than the one this page opened with: show it now.
            if (seen.current !== undefined && at !== seen.current && !quiet.current) router.refresh();
            seen.current = at;
          }
        } catch {
          // Asked again on the next tick.
        }
      }
      if (!stop) timer = setTimeout(tick, POLL_MS);
    };
    tick();
    return () => {
      stop = true;
      if (timer) clearTimeout(timer);
    };
  }, [router]);

  const prompt = pendingPrompt(live, dismissed);
  if (hidden || !prompt) return null;
  const { agents, project } = prompt;
  const names = agents.map((a) => a.name);
  const shown = names.length > 4 ? `${names.slice(0, 4).join(", ")} and ${names.length - 4} more` : names.join(", ");

  const add = async () => {
    setBusy(true);
    setError("");
    try {
      // The project init reported, else each agent on its own.
      const urls = project
        ? [`/api/projects/${encodeURIComponent(project)}/approve`]
        : agents.map((a) => `/api/projects/${encodeURIComponent(a.slug)}/approve`);
      for (const url of urls) {
        const r = await fetch(url, { method: "POST" });
        if (!r.ok) {
          setError(r.status === 403 ? "You can't add agents in this workspace. Ask someone who can." : "Couldn't add them. Try again.");
          return;
        }
      }
      if (project) document.cookie = `${MAP_PROJECT_COOKIE}=${encodeURIComponent(project)}; path=/; max-age=${PROJECT_COOKIE_AGE}; samesite=lax`;
      setLive((l) => (l ? { ...l, pending: [] } : l));
      router.push(projectHref(agents[0].slug));
      router.refresh();
    } catch {
      setError("Couldn't reach AgentFox. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const dismiss = () => {
    const next = [...readDismissed().slice(-19), prompt.key];
    try {
      localStorage.setItem(DISMISSED, JSON.stringify(next));
    } catch {
      // Hidden for this page view either way.
    }
    setDismissed(next);
  };

  return (
    <div className="protect-banner pending-agents" role="region" aria-label="Agents waiting to be added">
      <span>
        <strong>
          agentfox init found {agents.length === 1 ? "an agent" : `${agents.length} agents`}
          {project ? ` in ${project}` : ""}
        </strong>
        <span className="k-muted">
          {" "}
          · {shown}. Add {agents.length === 1 ? "it" : "them"} to guard and test {agents.length === 1 ? "it" : "them"}.
        </span>
        {error && (
          <span className="k-error" role="alert">
            {" "}
            {error}
          </span>
        )}
      </span>
      <span className="k-pills">
        <button type="button" className="k-btn-ghost" onClick={dismiss} title="They stay under Agents → Proposed">
          Not now
        </button>
        <Link href="/app/projects?tab=proposed" className="k-btn">
          Review
        </Link>
        <button type="button" className="k-btn-primary" onClick={add} disabled={busy}>
          {busy ? "Adding…" : addLabel(agents)}
        </button>
      </span>
    </div>
  );
}
