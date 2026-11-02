/**
 * An agent's status as the dashboard words it: Active, Paused or Stopped.
 *
 * The API keeps its own values (`active`, `quarantined`, `killed`, and the actions
 * `quarantine`, `kill`, `resume`); none of those words reach the screen. Pause and
 * Stop refuse calls identically and differ only in the intent they declare
 * ("investigating" vs "incident"), which an incident review asks about.
 *
 * Kept free of server-only imports: route handlers, server pages and client
 * components all read it.
 */

export type AgentState = "active" | "quarantined" | "killed";
export type ControlAction = "quarantine" | "kill" | "resume";

/** The agent's control record, as `GET /api/agent-controls` and `/api/agents/{slug}/control` return it. */
export type AgentControlRecord = {
  state?: string | null;
  previous_state?: string | null;
  reason?: string | null;
  actor?: string | null;
  changed_at?: string | null;
  breaker?: { mode?: string; state?: string; retry_at?: string | null; reason?: string | null; trips?: number } | null;
};

export const STATE_LABEL: Record<AgentState, string> = { active: "Active", quarantined: "Paused", killed: "Stopped" };

/** "Active" / "Paused" / "Stopped" for an API state; anything unknown reads as Active. */
export function stateLabel(state?: string | null): string {
  return STATE_LABEL[(state as AgentState) || "active"] ?? "Active";
}

export function isHalted(state?: string | null): boolean {
  return state === "quarantined" || state === "killed";
}

/** What each action is called, what it does, and its past tense for the notice. */
export const ACTION: Record<ControlAction, { verb: string; intent: string; title: string; confirm: string; done: string; does: string }> = {
  quarantine: {
    verb: "Pause",
    intent: "investigating",
    title: "Pause",
    confirm: "Pause agent",
    done: "paused",
    does: "Every call from this agent is refused until you resume.",
  },
  kill: {
    verb: "Stop",
    intent: "incident",
    title: "Stop",
    confirm: "Stop agent",
    done: "stopped",
    does: "Every call from this agent is refused until you resume. Same effect as Pause; it records that this is an incident.",
  },
  resume: {
    verb: "Resume",
    intent: "",
    title: "Resume",
    confirm: "Resume agent",
    done: "resumed",
    does: "Calls from this agent go through again, checked by its guardrails as before.",
  },
};

/** The API state an action leads to. */
export const STATE_AFTER: Record<ControlAction, AgentState> = { quarantine: "quarantined", kill: "killed", resume: "active" };

/**
 * The refusal reason the agent receives while halted, word for word as the gateway
 * builds it (`runtime/enforcement/limits.py` `_control_verdict`).
 */
export function refusalText(state: AgentState, reason?: string | null, actor?: string | null): string {
  return `Agent is ${{ quarantined: "paused", killed: "stopped" }[state as string] ?? state}` + (reason ? `: ${reason}` : "") + (actor ? ` (by ${actor})` : "");
}

/** The notice after an action: "Support agent paused." */
export function controlNotice(action: ControlAction, name?: string | null): string {
  const who = (name || "").trim().slice(0, 80) || "Agent";
  return `${who} ${ACTION[action].done}`;
}

/** A notice as the page shows it: a sentence, capitalised, with a full stop. */
export function noticeSentence(notice: string): string {
  const t = notice.trim();
  if (!t) return t;
  const s = t[0].toUpperCase() + t.slice(1);
  return /[.!?]$/.test(s) ? s : `${s}.`;
}

/**
 * Where to send the browser after a form post: the in-app page it came from, or the
 * fallback. Only same-origin `/app` paths pass (a form field or Referer naming
 * another host must not turn this domain into a redirector), and the previous
 * action's `review_notice` / `review_error` are dropped so they don't pile up.
 */
export function appReturnPath(candidate: string | null | undefined, origin: string, fallback: string): string {
  if (!candidate) return fallback;
  const raw = candidate.trim();
  if (!raw || raw.includes("\\") || /[\u0000-\u001f]/.test(raw)) return fallback;
  let url: URL;
  try {
    if (raw.startsWith("/")) {
      if (raw.startsWith("//")) return fallback;
      url = new URL(raw, origin);
    } else {
      url = new URL(raw);
    }
  } catch {
    return fallback;
  }
  if (url.origin !== new URL(origin).origin) return fallback;
  if (url.pathname !== "/app" && !url.pathname.startsWith("/app/")) return fallback;
  url.searchParams.delete("review_notice");
  url.searchParams.delete("review_error");
  const qs = url.searchParams.toString();
  return `${url.pathname}${qs ? `?${qs}` : ""}${url.hash}`;
}

/** The circuit breaker's settings, as `GET /api/agents/{slug}/breaker` returns them. */
export type BreakerConfig = {
  mode?: string;
  state?: string;
  block_ratio?: number;
  min_calls?: number;
  window_seconds?: number;
  cooldown_seconds?: number;
  probe_calls?: number;
};

const minutes = (s?: number) => {
  const m = Math.round((Number(s || 0) / 60) * 10) / 10;
  return `${m} min`;
};

/** The breaker's rule in one sentence: when it trips, and what happens then. */
export function breakerRule(b: BreakerConfig): string {
  if (b.mode === "off") return "The circuit breaker is off: a burst of blocked calls does nothing on its own.";
  const trips = `Trips when ${Math.round(Number(b.block_ratio || 0) * 100)}% of at least ${b.min_calls ?? 0} calls in ${minutes(b.window_seconds)} are blocked`;
  if (b.mode === "pause") {
    const n = b.probe_calls ?? 1;
    return `${trips}; then refuses this agent's calls for ${minutes(b.cooldown_seconds)} and lets them through again after ${n} clean call${n === 1 ? "" : "s"}.`;
  }
  return `${trips}; then raises an issue. Calls are not refused.`;
}

export const BREAKER_LABEL: Record<string, [string, "ok" | "bad" | "held"]> = {
  closed: ["Closed", "ok"],
  open: ["Open: calls refused", "bad"],
  probing: ["Probing", "held"],
};

/** The breaker's current state in words, with a tone. Open in alert mode refuses nothing. */
export function breakerLabel(b: BreakerConfig | null | undefined): [string, "ok" | "bad" | "held" | "outline"] {
  if (!b) return ["Not loaded", "outline"];
  if (b.mode === "off") return ["Off", "outline"];
  if (b.state === "open" && b.mode !== "pause") return ["Tripped: issue raised", "held"];
  return BREAKER_LABEL[b.state || "closed"] || BREAKER_LABEL.closed;
}

/** What the map's Agent panel shows about one agent. */
export type AgentFacts = {
  state: string;
  by?: string | null;
  at?: string | null;
  reason?: string | null;
  owner?: string | null;
  risk?: string | null;
  framework?: string | null;
  models: string[];
  breaker?: BreakerConfig | null;
  /** Open issues, when known (the focused agent's posture carries them). */
  openIssues?: number | null;
};
