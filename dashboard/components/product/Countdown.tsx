"use client";

import { useEffect, useState } from "react";
import { formatCountdown } from "@/lib/product/countdown";

/**
 * Ticks live rather than showing a static timestamp — a suppression or approval
 * that's about to lapse should read as urgent, not as a date someone has to do
 * math on. Renders the same static fallback on server and pre-hydration client
 * paint (no `now` yet) to avoid a hydration mismatch, then switches to the
 * countdown once mounted.
 */
export function Countdown({ at, fallback = "—" }: { at: string | null | undefined; fallback?: string }) {
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    setNow(new Date());
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(id);
  }, []);

  if (!at) return <span className="muted">{fallback}</span>;

  const target = new Date(at);
  if (!now) return <span className="small muted">{at.slice(0, 10)}</span>;

  const { label, tone } = formatCountdown(target, now);
  return (
    <span className={tone === "ok" ? "small muted" : `tag ${tone}`} title={target.toLocaleString()}>
      {label}
    </span>
  );
}
