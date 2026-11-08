/**
 * The public showcase feed behind /live.
 *
 * `GET /api/public/showcase` on the gateway is unauthenticated and returns only the
 * showcase tenant's counts (agentfox/apps/showcase.py). This module fetches it
 * server-side, with no cookie and no identity header, so the page is the same for
 * every visitor and can be cached and revalidated.
 *
 * Three states, and the page renders each one honestly rather than inventing a
 * number: the feed answered with data, the gateway says the showcase is not running,
 * or the gateway could not be reached.
 */
import { apiBase } from "@/lib/env";

export type ShowcaseRun = {
  id: string;
  finished_at: string | null;
  attacks_attempted: number;
  contained: number;
  escaped: number;
  errors: number;
  over_blocked: number;
  direction: "no_baseline" | "weaker" | "stronger" | "unchanged" | null;
  findings_opened: number;
  findings_closed: number;
};

export type ShowcaseResult = {
  key: string;
  category: string | null;
  severity: string | null;
  owasp_id: string | null;
  expect_blocked: boolean | null;
  status: "contained" | "escaped" | "error" | "skipped" | "answered" | "over_blocked";
  contained_by: "blocked" | "not_followed" | null;
  description: string;
};

export type ShowcaseFinding = {
  title: string;
  severity: string;
  status: string;
  probe: string | null;
  opened_at: string | null;
  resolved_at: string | null;
  occurrences: number;
};

export type Showcase = {
  enabled: true;
  last_updated: string | null;
  generated_at: string;
  window_days: number;
  agent: { slug: string; name: string; purpose: string };
  target: {
    adapter: string;
    model: string | null;
    scoring: string;
    interval_seconds: number | null;
    probes: string[];
  };
  totals: {
    runs: number;
    attacks_attempted: number;
    contained: number;
    escaped: number;
    errors: number;
    over_blocked: number;
  };
  latest: { run: ShowcaseRun | null; headline: string | null; results: ShowcaseResult[] };
  runs: ShowcaseRun[];
  findings: {
    open: number;
    opened_in_window: number;
    closed_in_window: number;
    recent: ShowcaseFinding[];
  };
  what_this_measures: string;
  how_scored: string;
};

export type ShowcaseFeed =
  | { state: "live"; data: Showcase }
  | { state: "off" }
  | { state: "unavailable"; reason: string };

/** How often the page asks the gateway again. The gateway caches for a minute. */
export const REVALIDATE_SECONDS = 300;

export function showcaseUrl(): string {
  const base = apiBase().replace(/\/+$/, "");
  return `${base}/api/public/showcase`;
}

/** Turn whatever the gateway answered into one of the three states. */
export function toFeed(status: number, body: unknown): ShowcaseFeed {
  if (status !== 200 || !body || typeof body !== "object") {
    return { state: "unavailable", reason: `the feed answered HTTP ${status}` };
  }
  const data = body as Partial<Showcase> & { enabled?: boolean };
  if (data.enabled !== true) return { state: "off" };
  if (!data.totals || !data.latest || !Array.isArray(data.runs) || !data.findings) {
    return { state: "unavailable", reason: "the feed answered in a shape this page does not know" };
  }
  return { state: "live", data: data as Showcase };
}

export async function fetchShowcase(): Promise<ShowcaseFeed> {
  try {
    const res = await fetch(showcaseUrl(), {
      headers: { Accept: "application/json" },
      next: { revalidate: REVALIDATE_SECONDS },
    });
    const body = res.ok ? await res.json() : null;
    return toFeed(res.status, body);
  } catch (err) {
    return { state: "unavailable", reason: err instanceof Error ? err.message : String(err) };
  }
}

/** "3 of 9", or "none of 9" — never a percentage of a number this small. */
export function ofTotal(part: number, total: number): string {
  if (total === 0) return "0";
  return part === 0 ? `none of ${total}` : `${part} of ${total}`;
}

export const DIRECTION_LABEL: Record<string, string> = {
  no_baseline: "First run",
  weaker: "Weaker",
  stronger: "Stronger",
  unchanged: "Unchanged",
};
