import { describe, expect, it } from "vitest";
import {
  IDLE_POLLS,
  POLL_MS,
  campaignNumbers,
  headline,
  notRunWhy,
  progressText,
  worseRows,
  cell,
  controlsLine,
  plainError,
  pollDelay,
  readyForApp,
  runNote,
  runState,
  shown,
  wouldStopNote,
  type ByType,
  type Run,
  type Tests,
} from "./attackTest";

const row = (over: Partial<ByType> = {}): ByType => ({
  type: "jailbreak",
  label: "Jailbreaks",
  total: 18,
  done: 18,
  gotThrough: 0,
  stopped: 0,
  resisted: 0,
  errored: 0,
  notRun: 0,
  wouldStop: 0,
  controls: 2,
  overBlocked: 0,
  controlsErrored: 0,
  ...over,
});

const run = (over: Partial<Run> = {}, rows: ByType[] = [row({ resisted: 18 })]): Run => ({
  id: "r1",
  status: "done",
  phase: "before",
  total: rows.reduce((n, r) => n + r.total, 0),
  byType: rows,
  waitingForRunner: false,
  error: null,
  ...over,
});

describe("a run where nothing ran", () => {
  // The agent couldn't be imported: every attack is "not run", the server fails the run.
  const nothing = run(
    {
      status: "failed",
      error:
        "No attack could be run, so this test says nothing about your agent yet. AgentFox couldn't import your agent (main.triage_agent): the module 'examples' it needs isn't installed where agentfox init runs.",
    },
    [row({ notRun: 18, notRunReason: "Not run: couldn't load main.triage_agent: ModuleNotFoundError: No module named 'examples'" })],
  );

  it("says Not run, neutral, never a green 0", () => {
    expect(runState(nothing)).toBe("not_run");
    const c = cell(nothing.byType[0], nothing);
    expect(c.text).toBe("Not run");
    expect(c.tone).toBe("neutral");
    expect(c.text).not.toMatch(/0\//);
  });

  it("explains why and how to fix it", () => {
    const note = runNote(nothing);
    expect(note?.text).toContain("isn't installed where agentfox init runs");
    expect(note?.tone).toBe("neutral");
  });

  it("reports no normal requests (none ran)", () => {
    expect(controlsLine(run({}, [row({ controls: 0 })]))).toBeNull();
  });
});

describe("a finished run", () => {
  it("is green only when the row ran clean", () => {
    const clean = run({}, [row({ resisted: 18 })]);
    expect(cell(clean.byType[0], clean)).toMatchObject({ text: "0/18", tone: "good", note: null });
  });

  it("counts errored and not-run attacks and is never green with them", () => {
    const r = run({ errored: 7, errorSummary: "Your agent's OpenAI API key was rejected, so the attacks couldn't run." }, [
      row({ resisted: 9, errored: 7, notRun: 2 }),
    ]);
    const c = cell(r.byType[0], r);
    expect(c.text).toBe("0/9");
    expect(c.tone).toBe("neutral");
    expect(c.note).toBe("7 errored · 2 not run");
    expect(runNote(r)?.text).toMatch(/^7 attacks errored and aren't counted: Your agent's OpenAI API key/);
  });

  it("is red when anything got through", () => {
    const r = run({}, [row({ gotThrough: 3, resisted: 15 })]);
    expect(cell(r.byType[0], r)).toMatchObject({ text: "3/18", tone: "bad" });
  });

  it("reports the normal requests answered and over-blocked", () => {
    const r = run({ controls: 11, overBlocked: 2 }, [row({ resisted: 18, controls: 11, overBlocked: 2 })]);
    expect(controlsLine(r)).toBe("9 of 11 normal requests answered, 2 blocked");
    expect(controlsLine(run({ controls: 8, overBlocked: 0 }))).toBe("8 of 8 normal requests answered");
  });
});

describe("a run that stopped part-way", () => {
  const partial = run({ status: "failed", error: "The test stopped: agentfox init stopped responding while it ran." }, [
    row({ done: 6, gotThrough: 2, resisted: 4 }),
  ]);

  it("keeps its partial numbers, never green", () => {
    expect(runState(partial)).toBe("partial");
    expect(cell(partial.byType[0], partial).text).toBe("2/6");
    const zero = run({ status: "failed", error: "stopped" }, [row({ done: 4, resisted: 4 })]);
    expect(cell(zero.byType[0], zero).tone).toBe("neutral");
  });

  it("says it stopped and what the numbers are from", () => {
    expect(runNote(partial)?.text).toContain("These numbers are from the 6 attacks that ran.");
  });
});

describe("watching guardrails", () => {
  it("says what they would stop once blocking", () => {
    expect(wouldStopNote(row({ wouldStop: 4 }), false)).toBe("would stop 4 once blocking");
    expect(wouldStopNote(row({ wouldStop: 4 }), true)).toBeNull();
    expect(wouldStopNote(row({ wouldStop: 0 }), false)).toBeNull();
  });
});

describe("raw provider errors", () => {
  it("become plain sentences", () => {
    expect(plainError("Error code: 401 - {'error': {'message': 'Incorrect API key provided'}}")).toMatch(/API key was rejected/);
    expect(plainError("openai.RateLimitError: Error code: 429 - {'error': {}}")).toMatch(/rate-limiting/);
    expect(plainError("{'error': {'code': 'insufficient_quota'}}")).toMatch(/out of credits/);
    expect(plainError("openai.APIStatusError: Error code: 500 - {'error': 'boom'}")).toMatch(/^Your agent returned an error/);
  });

  it("leave plain sentences alone", () => {
    expect(plainError("A test is already running for this project.")).toBe("A test is already running for this project.");
    expect(plainError(null)).toBeNull();
  });
});

describe("re-running", () => {
  const done = run({ id: "old" }, [row({ gotThrough: 25, resisted: 1, total: 26, done: 26 })]);
  const running = run({ id: "new", status: "running" }, [row({ done: 3, total: 26 })]);
  const tests = (over: Partial<Tests>): Tests => ({
    first: done,
    withBasic: null,
    basicOn: false,
    connectedProject: "cx",
    ...over,
  });

  it("keeps the last finished numbers while the new run goes", () => {
    expect(shown(tests({ first: running, firstPrevious: done })).before?.id).toBe("old");
    expect(shown(tests({ withBasic: running, withBasicPrevious: done })).after?.id).toBe("old");
    expect(shown(tests({})).before?.id).toBe("old");
  });
});

describe("polling", () => {
  const t = (over: Partial<Tests>): Tests => ({ first: null, withBasic: null, basicOn: false, connectedProject: "cx", ...over });

  it("watches a running test", () => {
    expect(pollDelay(t({ first: run({ status: "running" }) }), "cx", 0)).toBe(POLL_MS);
  });

  it("stops once there is a finished first test and nothing runs", () => {
    expect(pollDelay(t({ first: run() }), "cx", 0)).toBeNull();
    expect(pollDelay(t({ first: run({ status: "failed", error: "x" }) }), "cx", 0)).toBeNull();
  });

  it("never polls a project that can't run here, and gives up waiting after a while", () => {
    expect(pollDelay(t({ connectedProject: "other" }), "cx", 0)).toBeNull();
    expect(pollDelay(t({ runnerConnected: true }), "cx", 0)).not.toBeNull();
    expect(pollDelay(t({ runnerConnected: true }), "cx", IDLE_POLLS)).toBeNull();
  });
});

describe("red-team campaign numbers (Testing → Attack tests)", () => {
  it("is never a green 0 when no attack ran", () => {
    expect(campaignNumbers({ probes_run: 0, attacks_run: 0, attacks_succeeded: 0 })).toMatchObject({ ran: 0, tone: undefined });
  });

  it("counts watching blocks as getting through live traffic", () => {
    const n = campaignNumbers({
      attacks_run: 22,
      attacks_blocked: 11,
      attacks_succeeded: 11,
      attacks_stopped_live: 0,
      attacks_watching: 11,
      attacks_through_live: 22,
    });
    expect(n).toMatchObject({ stopped: 0, watching: 11, through: 22, tone: "bad" });
  });

  it("adds up: attacks = stopped + got through, normal requests apart, no 100% beside a breach", () => {
    // The demo sweep the audit saw: "22 tried, 7 stopped, 11 got through, Score 100%".
    const n = campaignNumbers({
      probes_run: 22,
      attacks_run: 18,
      attacks_blocked: 18,
      attacks_succeeded: 0,
      attacks_stopped_live: 7,
      attacks_watching: 11,
      attacks_through_live: 11,
      benign_probes_run: 4,
      benign_over_blocked_live: 0,
      posture_score: 1,
    });
    expect(n.ran).toBe(18);
    expect(n.stopped + n.through).toBe(n.ran);
    expect(n).toMatchObject({ controls: 4, answered: 4, watching: 11 });
    expect(n.stoppedShare).toBeCloseTo(7 / 18);
    expect(campaignNumbers({ attacks_run: 0 }).stoppedShare).toBeNull();
  });

  it("falls back to the old counts", () => {
    expect(campaignNumbers({ attacks_run: 5, attacks_blocked: 5, attacks_succeeded: 0 })).toMatchObject({ stopped: 5, through: 0, tone: "ok" });
  });
});

describe("the panel's headline and notes", () => {
  const jb = (over: Partial<ByType>) => row({ type: "jailbreak", label: "Jailbreaks", total: 36, done: 36, controls: 6, ...over });
  const leak = (over: Partial<ByType>) => row({ type: "data_leak", label: "Data leaks", total: 18, done: 18, controls: 6, ...over });
  const before = run({}, [jb({ gotThrough: 1, resisted: 35 }), leak({ gotThrough: 12, resisted: 6 })]);
  const after = run({ phase: "after" }, [jb({ gotThrough: 3, stopped: 33 }), leak({ gotThrough: 0, stopped: 18 })]);

  it("leads with the total, before → after, and the normal requests", () => {
    expect(headline(before, after)).toBe("13 → 3 attacks got through · 12 of 12 normal requests still answered");
    expect(headline(before, null)).toBe("13 of 54 attacks got through · 12 of 12 normal requests answered");
    expect(headline(null, null)).toBeNull();
  });

  it("names a set that got worse, so the variation is shown rather than hidden", () => {
    expect(worseRows(before, after)).toEqual([{ label: "Jailbreaks", before: "1/36", after: "3/36" }]);
  });

  it("says why attacks were not run, next to the count", () => {
    expect(notRunWhy(row({ notRun: 2, notRunReason: "Needs a tool that sends email." }))).toBe("2 not run: Needs a tool that sends email");
    expect(notRunWhy(row({ notRun: 0 }))).toBeNull();
  });

  it("shows progress as progress", () => {
    expect(progressText(row({ total: 36, done: 12 }))).toBe("testing 12 of 36");
    expect(progressText(row({ total: 36, done: 36 }))).toBeNull();
  });
});

describe("the step after the before/after", () => {
  it("points at running the app once both runs have finished with basic guardrails on", () => {
    expect(readyForApp({ beforeRan: true, afterRan: true, basicOn: true, live: false })).toBe(true);
    expect(readyForApp({ beforeRan: true, afterRan: false, basicOn: true, live: false })).toBe(false);
    expect(readyForApp({ beforeRan: true, afterRan: true, basicOn: true, live: true })).toBe(false);
  });
});
