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

/** How many of the first, watch-only guardrails an agent has; a rule on two steps counts once. */
export function watchingCount(stages: { rules?: { id: string }[] }[] | undefined): number {
  return new Set((stages ?? []).flatMap((s) => s.rules ?? []).map((r) => String(r.id)).filter((id) => id.startsWith("watch."))).size;
}
