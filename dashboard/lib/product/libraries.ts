/**
 * Words for a library's contents and where it stands, shared by the library cards,
 * the drawer they open and a library's own page (/app/policies/<library>).
 */

/** One rule as `GET /api/library/packs/<id>/contents` lists it. */
export type LibraryRule = {
  id: string;
  description?: string;
  surfaces: string[];
  effect: string;
  severity?: string | null;
  tool?: string | null;
  /** A business rule's bands, said in a line ("up to 10 USD: allow · …"). */
  detail?: string;
  /** For a business rule: whether it is saved, and watching or enforcing. */
  installed?: boolean;
  mode?: string | null;
};

/** What a library's last "Simulate" found (the simulate route's answer, and `simulation`). */
export type SimulationResult = { replayed: number; blocked: number; held: number; hidden: number; since_days: number; at?: string };

export type LibraryContents = {
  id: string;
  title: string;
  description: string;
  /** False for a library of business rules only: those apply to every agent. */
  scoped: boolean;
  rules: LibraryRule[];
  simulation: SimulationResult | null;
};

/** Where a library stands on the chosen project's agents (`/api/policies/libraries/status`). */
export type LibraryStatus = { agents: string[]; blocking: boolean; workspace: boolean; outdated?: boolean; outdatedAgents?: string[] };

const CHECKS: Record<string, string> = {
  input: "User messages",
  output: "Replies",
  completion: "Task completion",
  tool_call: "Tool calls",
  tool_args: "Tool calls",
  tool_result: "Tool results",
  retrieved: "Retrieved content",
  memory_write: "Memory writes",
  agent_message: "Agent-to-agent messages",
  reasoning: "Reasoning",
  mcp: "MCP calls",
};

/** What a rule looks at: "User messages, Replies"; a tool rule with no surface is on tool calls. */
export function checksLabel(rule: Pick<LibraryRule, "surfaces" | "tool">): string {
  const named = Array.from(new Set((rule.surfaces || []).map((s) => CHECKS[s] || s)));
  if (named.length) return named.join(", ");
  return rule.tool ? "Tool calls" : "Every check";
}

const DOES: Record<string, string> = {
  block: "Block",
  escalate: "Ask a person",
  verify: "Run a check",
  redact: "Hide",
  mask: "Hide",
  tokenize: "Hide",
  abstain: "Refuse",
  allow: "Allow",
};

/** What a rule does when it fires, as a person would say it. */
export function doesLabel(effect: string): string {
  return DOES[effect] || effect;
}

const WOULD_DO: Record<string, string> = {
  block: "Would block",
  escalate: "Would ask a person",
  verify: "Would run a check",
  redact: "Would hide",
  mask: "Would hide",
  tokenize: "Would hide",
  abstain: "Would refuse",
  allow: "Allow",
};

/** What a rule would do while its library only watches: "Would block". */
export function wouldDoLabel(effect: string): string {
  return WOULD_DO[effect] || `Would ${doesLabel(effect).toLowerCase()}`;
}

/** "Would have blocked 3, asked a person about 1 and hidden data in 2 of 140 checks". */
export function simulationSummary(r: SimulationResult): string {
  if (!r.replayed) return `No traffic in the last ${r.since_days} days to replay. Blocking is allowed now; nothing tells you yet what it will stop.`;
  const parts = [`blocked ${r.blocked}`, r.held ? `asked a person about ${r.held}` : "", r.hidden ? `hidden data in ${r.hidden}` : ""].filter(Boolean);
  const last = parts.length > 1 ? ` and ${parts.pop()}` : "";
  return `Last ${r.since_days} days: would have ${parts.join(", ")}${last} of ${r.replayed} checks.`;
}

/** "the agent", "all 3 agents" or "2 of 3 agents" of the project. */
export function whereOn(n: number, total: number): string {
  if (n === total) return total === 1 ? "the agent" : `all ${total} agents`;
  return `${n} of ${total} agents`;
}

/** The card's one-line state: "On all 3 agents · watching · update available", or "Not applied". */
export function libraryState(st: LibraryStatus, total: number): { text: string; tone: "" | "pol-on" | "pol-watch" } {
  const mode = st.blocking ? "blocking" : "watching";
  const tone = st.blocking ? "pol-on" : "pol-watch";
  if (st.agents.length) return { text: `On ${whereOn(st.agents.length, total)} · ${mode}${st.outdated ? " · update available" : ""}`, tone };
  if (st.workspace) return { text: `On every agent (workspace) · ${mode}`, tone };
  return { text: "Not applied", tone: "" };
}

/** Applied rules shown: all, only the ones that act now, or only the ones watching. */
export type AppliedMode = "" | "enforce" | "observe";

type AppliedRow = { id: string; effect: string; mode: string; libraries: string[] };

/**
 * Applied rules by the library they come from, so a page of fifty reads as a few
 * sets: the groups that act first, then by size; inside one, acting rules first.
 * A rule in several libraries is listed under the first.
 */
export function groupApplied<T extends AppliedRow>(rows: T[]): { library: string; rules: T[]; blocking: number }[] {
  const acts = (r: AppliedRow) => r.mode !== "observe" && r.effect !== "allow";
  const by = new Map<string, T[]>();
  for (const r of rows) {
    const lib = r.libraries[0] || "Other rules";
    by.set(lib, [...(by.get(lib) || []), r]);
  }
  return Array.from(by.entries())
    .map(([library, rules]) => ({
      library,
      rules: [...rules].sort((a, b) => Number(acts(b)) - Number(acts(a))),
      blocking: rules.filter(acts).length,
    }))
    .sort((a, b) => Number(b.blocking > 0) - Number(a.blocking > 0) || b.rules.length - a.rules.length || a.library.localeCompare(b.library));
}

/** A library id as a URL path: `payments/refunds` keeps its slash. */
export function libraryPath(id: string): string {
  return encodeURIComponent(id).replace(/%2F/g, "/");
}

/**
 * Requests a pack's own rules would have stopped, from a policy simulation. Not
 * `newly_blocked`: that compares with what each call would already have had, so a
 * watching rule's own catches read 0 ("0 would have been stopped" right after a
 * words rule flagged a message). An older gateway without the own count falls back
 * to every stop the replay found.
 */
export function packWouldStop(sim: any): number {
  return sim?.runs_own_would_stop ?? sim?.counts?.own_would_stop ?? sim?.runs_would_stop ?? sim?.counts?.would_stop ?? 0;
}

/**
 * Your rules' one-line state from each rule's own mode: "2 rules · blocking" only
 * when every one blocks, "2 rules · 1 blocking, 1 watching" when they differ. The
 * words rules share the custom pack's mode; each business rule has its own.
 */
export function ownRulesState(modes: (string | null | undefined)[]): { text: string; tone: "" | "pol-on" | "pol-watch"; mode: "blocking" | "watching" | "mixed" | null } {
  const n = modes.length;
  if (!n) return { text: "No rules yet", tone: "", mode: null };
  const count = `${n} ${n === 1 ? "rule" : "rules"}`;
  const blocking = modes.filter((m) => m === "enforce").length;
  if (blocking === n) return { text: `${count} · blocking`, tone: "pol-on", mode: "blocking" };
  if (!blocking) return { text: `${count} · watching`, tone: "pol-watch", mode: "watching" };
  return { text: `${count} · ${blocking} blocking, ${n - blocking} watching`, tone: "pol-watch", mode: "mixed" };
}

/** Calls a business rule would have held, from its simulation (POST …/simulate). */
export function businessWouldStop(sim: any): number {
  return sim?.counts?.would_stop ?? 0;
}
