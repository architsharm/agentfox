"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

type Counts = { traces: number; agents: number; decisions: number };

/**
 * The moment setup either worked or did not. Before this, a developer pasted a
 * snippet, ran their agent, and then had to go looking — Activity, Agents,
 * Issues — to find out whether anything arrived. This waits for them: it polls
 * while nothing has been received and turns green the moment something is.
 *
 * Polling stops once traffic is seen, when the tab is hidden, and after ten
 * minutes, so a forgotten tab does not keep asking forever.
 */
const INTERVAL_MS = 4000;
const GIVE_UP_MS = 10 * 60_000;

export function FirstRequestWatcher({ initial }: { initial: Counts }) {
  const [counts, setCounts] = useState(initial);
  const [gaveUp, setGaveUp] = useState(false);
  const received = counts.traces > 0;

  useEffect(() => {
    if (received) return;
    const started = Date.now();
    const timer = setInterval(async () => {
      if (Date.now() - started > GIVE_UP_MS) {
        setGaveUp(true);
        clearInterval(timer);
        return;
      }
      if (document.hidden) return;
      try {
        const res = await fetch("/api/onboarding", { cache: "no-store" });
        if (!res.ok) return;
        const body = await res.json();
        if (body?.counts) setCounts(body.counts);
      } catch {
        // Transient: the next tick tries again.
      }
    }, INTERVAL_MS);
    return () => clearInterval(timer);
  }, [received]);

  if (received) {
    return (
      <div className="watcher watcher-ok" role="status">
        <span className="watcher-dot" aria-hidden />
        <div>
          <strong>Receiving traffic.</strong>{" "}
          <span className="muted">
            {counts.traces} request(s) from {counts.agents} agent(s), {counts.decisions} decision(s) recorded.
          </span>
        </div>
        <div className="watcher-actions">
          <Link href="/app/traces">See activity →</Link>
          <Link href="/app/agents">Review agents →</Link>
        </div>
      </div>
    );
  }
  return (
    <div className="watcher" role="status" aria-live="polite">
      <span className="watcher-dot watcher-pulse" aria-hidden />
      <div>
        <strong>{gaveUp ? "Nothing received yet." : "Waiting for your first request…"}</strong>{" "}
        <span className="muted">
          {gaveUp
            ? "Reload this page to keep waiting. Check the gateway URL and API key in your snippet."
            : "Run your agent with one of the snippets above. This updates by itself."}
        </span>
      </div>
    </div>
  );
}
