/**
 * The setup card's decisions, as plain functions so they can be tested without a
 * browser: what an error should say, whether `agentfox init` has just reported in,
 * and how many first guardrails a fresh agent got.
 */

/** What a failed onboarding request should tell the user. */
export function requestError(status: number | null, body: { detail?: unknown; error?: unknown } = {}): string {
  // No answer at all, or the dashboard couldn't reach the AgentFox server behind it.
  if (status === null || status === 502 || status === 503 || status === 504)
    return "Can't reach the AgentFox server right now. Check it is running, then try again.";
  if (status === 401 || status === 403) return "Your session has ended. Sign in again, then try again.";
  const detail = typeof body.detail === "string" ? body.detail : typeof body.error === "string" ? body.error : "";
  return detail || `Something went wrong (${status}). Try again.`;
}

/** What the structure endpoint said when the card opened. */
export type Baseline = { connected: boolean; at: string | null };
/** What it says on a poll. */
export type Live = { connected: boolean; connectedAt?: string | null; structure: { agents: unknown[] } };

/**
 * Has `agentfox init` reported in since the card opened? A connection that was
 * already there when the page loaded is not "you just ran it". Unknown baseline:
 * not yet (we don't guess).
 */
export function isFreshConnection(baseline: Baseline | null, live: Live): boolean {
  if (!baseline || !live.connected || live.structure.agents.length === 0) return false;
  if (live.connectedAt) return !baseline.at || live.connectedAt > baseline.at;
  return !baseline.connected;
}

/** GET /api/onboarding/structure, as the "add what init found" prompt reads it. */
export type Arrival = {
  connected: boolean;
  connectedAt?: string | null;
  structure: { project?: string | null };
  /** The reported agents that are still drafts: proposed, not added yet. */
  pending?: { slug: string; name: string }[];
};

/** What the prompt asks about: one init report, named by its project and time. */
export type PendingPrompt = { key: string; project: string | null; agents: { slug: string; name: string }[] };

/**
 * The agents `agentfox init` found that still wait to be added, unless this report
 * was dismissed. The prompt stays (on every page, across reloads) until they are
 * added or it is dismissed; a later init (another repository, or the same one run
 * again) asks again.
 */
export function pendingPrompt(live: Arrival | null, dismissed: string[]): PendingPrompt | null {
  if (!live?.connected || !live.pending?.length) return null;
  const project = live.structure?.project ?? null;
  const key = `${project ?? ""}@${live.connectedAt ?? ""}`;
  if (dismissed.includes(key)) return null;
  return { key, project, agents: live.pending };
}

/** "Add 3 agents to AgentFox" / "Add Shop Agent to AgentFox". */
export function addLabel(agents: { name: string }[]): string {
  return agents.length === 1 ? `Add ${agents[0].name} to AgentFox` : `Add ${agents.length} agents to AgentFox`;
}
