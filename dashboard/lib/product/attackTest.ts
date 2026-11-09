/**
 * What the attack test panel (`components/product/agent/AttackTests.tsx`) says about a
 * run, kept apart from the component so it can be tested.
 *
 * The rule throughout: a number is green only when attacks actually ran to a verdict
 * and nothing errored. A run where nothing ran says "Not run" (never "0/26"), errored
 * and not-run attacks are counted out loud, and the ordinary requests the guardrails
 * must let through are reported beside the attacks.
 */

/** One attack set in a run, as `/api/onboarding/projects/{p}/tests` sends it. */
export type ByType = {
  type: string;
  label: string;
  total: number;
  done: number;
  gotThrough: number;
  stopped?: number;
  resisted?: number;
  errored?: number;
  notRun?: number;
  wouldStop?: number;
  controls?: number;
  overBlocked?: number;
  controlsErrored?: number;
  controlsTotal?: number;
  notRunReason?: string | null;
};

export type Run = {
  id: string;
  status: "running" | "done" | "failed";
  phase: "before" | "after";
  total: number;
  /** Normal requests in the suite (benign controls), beside `total` attacks. */
  controlsTotal?: number;
  byType: ByType[];
  waitingForRunner: boolean;
  error: string | null;
  gotThrough?: number;
  stopped?: number;
  resisted?: number;
  errored?: number;
  notRun?: number;
  wouldStop?: number;
  controls?: number;
  overBlocked?: number;
  falsePositiveRate?: number | null;
  clean?: boolean;
  ran?: number;
  errorSummary?: string | null;
  skipped?: { type: string; agent: string; reason: string }[];
};

export type Tone = "good" | "bad" | "neutral";

/** How a run ended, as the panel tells it. */
export type RunState = "running" | "not_run" | "partial" | "done";

const ranOf = (t: { gotThrough?: number; stopped?: number; resisted?: number }) =>
  (t.gotThrough ?? 0) + (t.stopped ?? 0) + (t.resisted ?? 0);

/** Attacks in the run that reached a verdict (got through, stopped or resisted). */
export function ran(run: Run): number {
  if (typeof run.ran === "number") return run.ran;
  return run.byType.reduce((n, t) => n + ranOf(t), 0);
}

export function runState(run: Run): RunState {
  if (run.status === "running") return "running";
  if (ran(run) === 0) return "not_run";
  if (run.status === "failed") return "partial";
  return "done";
}

export type Cell = {
  /** "3/26", "Not run", "Errored", "—". */
  text: string;
  tone: Tone;
  /** Shown small under the number: "2 errored · 1 not run". */
  note: string | null;
  title: string;
};

/** One side (before or after) of a row's result. */
export function cell(row: ByType | undefined, run: Run | null | undefined): Cell {
  if (!row || !run) return { text: "—", tone: "neutral", note: null, title: "" };
  const reached = ranOf(row);
  const errored = row.errored ?? 0;
  const notRun = row.notRun ?? 0;
  const state = runState(run);
  if (reached === 0) {
    if (errored > 0 && errored >= notRun) {
      return {
        text: "Errored",
        tone: "neutral",
        note: null,
        title: `${errored} of ${row.total} attacks errored before reaching a verdict`,
      };
    }
    return {
      text: "Not run",
      tone: "neutral",
      note: null,
      title: plainError(row.notRunReason || run.error) || "These attacks weren't run.",
    };
  }
  const parts = [errored ? `${errored} errored` : "", notRun ? `${notRun} not run` : ""].filter(Boolean);
  const partial = state === "partial" || state === "running";
  // Green only for a finished run where everything in the row ran and none got through.
  const tone: Tone = row.gotThrough > 0 ? "bad" : !partial && errored === 0 && notRun === 0 ? "good" : "neutral";
  const title =
    `${row.gotThrough} of ${reached} attacks that ran got through` +
    (parts.length ? `; ${parts.join(", ")}` : "") +
    (state === "partial" ? " (the test stopped before it finished)" : "");
  return { text: `${row.gotThrough}/${reached}`, tone, note: parts.length ? parts.join(" · ") : null, title };
}

/** "would stop 4 once blocking": attacks a watching rule would stop once it blocks. */
export function wouldStopNote(row: ByType | undefined, basicEnforcing: boolean | undefined): string | null {
  if (!row || basicEnforcing) return null;
  const n = row.wouldStop ?? 0;
  return n > 0 ? `would stop ${n} once blocking` : null;
}

/** "9 of 11 normal requests answered, 2 blocked", or null when none ran. */
export function controlsLine(run: Run | null | undefined): string | null {
  if (!run) return null;
  const total = run.controls ?? run.byType.reduce((n, t) => n + (t.controls ?? 0), 0);
  if (!total) return null;
  const blocked = run.overBlocked ?? run.byType.reduce((n, t) => n + (t.overBlocked ?? 0), 0);
  const errored = run.byType.reduce((n, t) => n + (t.controlsErrored ?? 0), 0);
  const answered = total - blocked - errored;
  return (
    `${answered} of ${total} normal request${total === 1 ? "" : "s"} answered` +
    (blocked ? `, ${blocked} blocked` : "") +
    (errored ? `, ${errored} errored` : "")
  );
}

/** What to say under the rows about a run that didn't simply finish clean. */
export function runNote(run: Run | null | undefined): { text: string; tone: "warn" | "neutral" } | null {
  if (!run) return null;
  const state = runState(run);
  if (state === "running") return null;
  if (state === "not_run") {
    const errored = run.errored ?? run.byType.reduce((n, t) => n + (t.errored ?? 0), 0);
    if (errored && !run.error) {
      return { text: plainError(run.errorSummary) || "Every attack errored before reaching a verdict.", tone: "warn" };
    }
    // Shown after a bold "Not run.", so the server's lead-in isn't said twice.
    const why = (plainError(run.error) || "").replace(/^No attack could be run(: |, so )/, "");
    return {
      text: why ? why[0].toUpperCase() + why.slice(1) : "This test says nothing about your agent yet.",
      tone: "neutral",
    };
  }
  if (state === "partial") {
    return {
      text:
        `The test stopped before it finished: ${plainError(run.error) || "it couldn't reach your agent."} ` +
        `These numbers are from the ${ran(run)} attacks that ran.`,
      tone: "warn",
    };
  }
  const errored = run.errored ?? 0;
  if (errored) {
    const why = plainError(run.errorSummary);
    return {
      text: `${errored} attack${errored === 1 ? "" : "s"} errored and aren't counted${why ? `: ${why}` : "."}`,
      tone: "warn",
    };
  }
  return null;
}

/**
 * A sentence for an error that may be a provider's raw message ("Error code: 401 -
 * {'error': ...}"), a stack trace or a JSON body. Plain sentences pass through.
 */
export function plainError(message: string | null | undefined): string | null {
  if (!message) return null;
  const text = message.trim();
  const raw =
    /error code:\s*\d{3}/i.test(text) ||
    /\{['"]error['"]\s*:/.test(text) ||
    /traceback \(most recent call last\)/i.test(text) ||
    /^[\w.]+(Error|Exception):/.test(text) ||
    /^\s*[{[]/.test(text);
  if (!raw) return text;
  const lower = text.toLowerCase();
  const status = Number((/(?:error code|status(?: code)?)[:\s]+(\d{3})/i.exec(text) || [])[1]) || null;
  if (status === 402 || lower.includes("insufficient_quota") || lower.includes("exceeded your current quota")) {
    return "Your agent's model account is out of credits, so the attacks couldn't reach its model. Add credits, then try again.";
  }
  if (status === 401 || status === 403 || lower.includes("invalid_api_key") || lower.includes("incorrect api key")) {
    return "Your agent's API key was rejected, so the attacks couldn't run. Check the key in your agent's environment, then try again.";
  }
  if (status === 429 || lower.includes("rate limit") || lower.includes("rate_limit")) {
    return "Your agent's model is rate-limiting requests right now. Wait a minute, then try again.";
  }
  if (lower.includes("timed out") || lower.includes("timeout") || lower.includes("connection error")) {
    return "Your agent couldn't reach its model (network error). Check your connection, then try again.";
  }
  return "Your agent returned an error the test couldn't use. Check that your agent runs on its own, then try again.";
}

export type Tests = {
  first: Run | null;
  withBasic: Run | null;
  firstPrevious?: Run | null;
  withBasicPrevious?: Run | null;
  basicOn: boolean;
  basicEnforcing?: boolean;
  connectedProject: string | null;
  runnerConnected?: boolean;
};

/** The running run, if any. */
/** Attacks in a run that got through. */
export function gotThroughOf(run: Run): number {
  return typeof run.gotThrough === "number" ? run.gotThrough : run.byType.reduce((n, t) => n + (t.gotThrough ?? 0), 0);
}

/**
 * The panel's one-line result: "22 → 9 attacks got through · 12 of 12 normal
 * requests still answered". Rows alone left the reader to add up four fractions to
 * find out whether the guardrails helped. Null until a run has reached a verdict.
 */
export function headline(before: Run | null | undefined, after: Run | null | undefined): string | null {
  const b = before && runState(before) !== "not_run" ? before : null;
  const a = after && runState(after) !== "not_run" ? after : null;
  if (!b && !a) return null;
  const attacks = b && a
    ? `${gotThroughOf(b)} → ${gotThroughOf(a)} attacks got through`
    : `${gotThroughOf((a || b)!)} of ${ran((a || b)!)} attacks got through`;
  const last = a || b!;
  const total = last.controls ?? last.byType.reduce((n, t) => n + (t.controls ?? 0), 0);
  if (!total) return attacks;
  const blocked = last.overBlocked ?? last.byType.reduce((n, t) => n + (t.overBlocked ?? 0), 0);
  const errored = last.byType.reduce((n, t) => n + (t.controlsErrored ?? 0), 0);
  const answered = total - blocked - errored;
  return `${attacks} · ${answered} of ${total} normal request${total === 1 ? "" : "s"} ${a && b ? "still " : ""}answered`;
}

/** "36 not run: needs a tool that sends email": the reason beside the count. */
export function notRunWhy(row: ByType | undefined): string | null {
  const n = row?.notRun ?? 0;
  if (!row || !n) return null;
  // The reason may still carry its own "Not run:" lead (an older server): said once.
  const why = plainError(row.notRunReason)?.replace(/^not run:\s*/i, "");
  return why ? `${n} not run: ${why.replace(/\.$/, "")}` : `${n} not run`;
}

/**
 * One past run as Testing → Attack tests lists it: the same numbers the agent page's
 * panel shows for that run (attacks that reached a verdict, how many got through, how
 * many were stopped), the normal requests, and what wasn't run.
 */
export function runRow(run: Run): {
  attacks: number;
  ran: number;
  stopped: number;
  through: number;
  notRun: number;
  errored: number;
  normal: string | null;
  state: RunState;
} {
  return {
    attacks: run.total,
    ran: ran(run),
    stopped: run.stopped ?? run.byType.reduce((n, t) => n + (t.stopped ?? 0), 0),
    through: gotThroughOf(run),
    notRun: run.notRun ?? run.byType.reduce((n, t) => n + (t.notRun ?? 0), 0),
    errored: run.errored ?? run.byType.reduce((n, t) => n + (t.errored ?? 0), 0),
    normal: controlsLine(run),
    state: runState(run),
  };
}

/**
 * Sets where more got through with the guardrails on than without. The guardrails
 * didn't make the agent weaker; a live model answers the same attack differently
 * from one run to the next, and the panel says so instead of hiding the row.
 */
export function worseRows(before: Run | null | undefined, after: Run | null | undefined): { label: string; before: string; after: string }[] {
  if (!before || !after) return [];
  const out: { label: string; before: string; after: string }[] = [];
  for (const a of after.byType) {
    const b = before.byType.find((t) => t.type === a.type);
    if (!b || !ranOf(a) || !ranOf(b)) continue;
    if (a.gotThrough > b.gotThrough) {
      out.push({ label: a.label, before: `${b.gotThrough}/${ranOf(b)}`, after: `${a.gotThrough}/${ranOf(a)}` });
    }
  }
  return out;
}

/** "Testing: 12 of 36" while a set runs; shown as progress, never as a result. */
export function progressText(live: ByType | undefined): string | null {
  if (!live || live.done >= live.total) return null;
  return `testing ${live.done} of ${live.total}`;
}

export function liveRun(tests: Tests | null): Run | null {
  if (tests?.first?.status === "running") return tests.first;
  if (tests?.withBasic?.status === "running") return tests.withBasic;
  return null;
}

/**
 * The runs the rows show: the latest of each phase, or while one runs again the last
 * one that finished, so its numbers stay until the new ones are in.
 */
export function shown(tests: Tests): { before: Run | null; after: Run | null } {
  const before = tests.first?.status === "running" ? tests.firstPrevious ?? null : tests.first;
  const after = tests.withBasic?.status === "running" ? tests.withBasicPrevious ?? null : tests.withBasic;
  return { before, after };
}

/**
 * A red-team campaign's numbers (Testing → Attack tests) as live traffic gets them: a
 * block by a rule that only watches is not "stopped", and a campaign where no attack
 * ran is never a green 0. Campaigns from before the live counts were kept fall back to
 * the counterfactual ones.
 */
export function campaignNumbers(summary: Record<string, any> | null | undefined): {
  ran: number;
  stopped: number;
  watching: number;
  through: number;
  tone: "ok" | "bad" | undefined;
  /** Normal requests in the run (benign controls), and how many were answered. */
  controls: number;
  answered: number;
  /** Share of attacks stopped live, 0..1, or null when none ran. Replaces "Score",
   *  which was recall counting watching catches as stopped: "100%" beside "11 got
   *  through". */
  stoppedShare: number | null;
} {
  const s = summary || {};
  // Attacks only: `probes_run` also counts the normal requests, which made "22 tried"
  // sit above 7 stopped + 11 got through.
  const ran = Number(s.attacks_run ?? s.probes_run ?? 0) || 0;
  const live = typeof s.attacks_stopped_live === "number";
  const stopped = live ? s.attacks_stopped_live : Number(s.attacks_blocked || 0);
  const watching = live ? Number(s.attacks_watching || 0) : 0;
  const through = live ? Number(s.attacks_through_live || 0) : Number(s.attacks_succeeded || 0);
  const controls = Number(s.benign_probes_run || 0) || 0;
  const blocked = Number(
    (typeof s.benign_over_blocked_live === "number" ? s.benign_over_blocked_live : s.benign_false_positives) || 0,
  );
  return {
    ran,
    stopped,
    watching,
    through,
    tone: !ran ? undefined : through ? "bad" : "ok",
    controls,
    answered: Math.max(0, controls - blocked),
    stoppedShare: ran ? stopped / ran : null,
  };
}

export const POLL_MS = 1500;
/** Waiting for the first test of a project whose `agentfox init` is connected. */
export const WAIT_MS = 4000;
/** Waiting with no runner seen: slow, and only for a while. */
export const IDLE_MS = 15000;
/** Polls without anything running before the panel stops asking (it asks again on focus). */
export const IDLE_POLLS = 40;

/**
 * How long until the panel asks again, or null to stop. It watches while a test runs
 * and while the first one is still to start; a project that can't run (no `agentfox
 * init` here) isn't polled at all.
 */
export function pollDelay(tests: Tests | null, project: string, idlePolls: number): number | null {
  if (!tests) return null;
  if (liveRun(tests)) return POLL_MS;
  if (tests.first) return null;
  if (tests.connectedProject !== project) return null;
  if (idlePolls >= IDLE_POLLS) return null;
  return tests.runnerConnected ? WAIT_MS : IDLE_MS;
}

/**
 * After the before/after pair (no guardrails, then basic guardrails) has finished, the
 * panel's next step is the app itself: add `auto()`, run it, watch Activity. Nothing
 * pointed there before, so the first wow ended on a number.
 */
export function readyForApp(o: { beforeRan: boolean; afterRan: boolean; basicOn: boolean; live: boolean }): boolean {
  return o.beforeRan && o.afterRan && o.basicOn && !o.live;
}
