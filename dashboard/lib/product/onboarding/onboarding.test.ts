import { describe, expect, it } from "vitest";
import { STRUCTURE, TOTAL_ATTACKS, parseRunId, runId, simulateConnect, simulateRun } from "./fixtures";
import { INITIAL_STATE, completeStep, riskyToolCount, suggestGuardrails } from "./steps";
import { EMPTY_SESSION, parseSession, pollStructure, startRun } from "./store";
import { flagOn } from "../flags";

describe("onboarding fixtures", () => {
  it("before: 41 of 140, with the brief's breakdown", () => {
    const run = simulateRun("run-before-0", "before", 10_000);
    expect(run.status).toBe("done");
    expect([run.gotThrough, run.total]).toEqual([41, 140]);
    expect(run.byType.map((t) => `${t.gotThrough}/${t.total}`)).toEqual(["17/40", "12/40", "9/30", "3/30"]);
    expect(run.worst?.headline).toMatch(/\$5,000/);
  });

  it("after: 3 of 140, as 1, 1, 0, 1", () => {
    const run = simulateRun("run-after-0", "after", 10_000);
    expect(run.gotThrough).toBe(3);
    expect(run.byType.map((t) => t.gotThrough)).toEqual([1, 1, 0, 1]);
  });

  it("runs take about 8 seconds and add a feed line every half second", () => {
    expect(simulateRun("x", "before", 0).feed).toHaveLength(1);
    expect(simulateRun("x", "before", 2_100).feed).toHaveLength(5);
    expect(simulateRun("x", "before", 7_900).status).toBe("running");
    expect(simulateRun("x", "before", 8_000).status).toBe("done");
    expect(TOTAL_ATTACKS).toBe(140);
  });

  it("connect waits 3 seconds, then fills the counts in over 2 more", () => {
    expect(simulateConnect(2_900).connected).toBe(false);
    const partway = simulateConnect(4_000);
    expect(partway.connected).toBe(true);
    expect(partway.structure.tools.length).toBeLessThan(STRUCTURE.tools.length);
    expect(simulateConnect(5_000).structure).toEqual(STRUCTURE);
  });

  it("run ids carry phase and start time", () => {
    expect(parseRunId(runId("after", 123))).toEqual({ phase: "after", startedAt: 123 });
    expect(parseRunId("nonsense")).toBeNull();
  });
});

describe("onboarding steps", () => {
  it("completing a step moves on, and the last one completes onboarding", () => {
    const s1 = completeStep(INITIAL_STATE, "connect");
    expect(s1).toMatchObject({ currentStep: "install", completedSteps: ["connect"], completedAt: null });
    const last = completeStep({ ...s1, currentStep: "retest" }, "retest");
    expect(last.currentStep).toBe("retest");
    expect(last.completedAt).not.toBeNull();
  });

  it("suggests the three tool guardrails only when those tools exist", () => {
    expect(riskyToolCount(STRUCTURE)).toBe(3);
    expect(suggestGuardrails(STRUCTURE).map((g) => g.sentence)).toEqual([
      "Refunds over $100 need a person",
      "Block bulk customer exports",
      "Block DELETE / DROP from sql-agent",
      "Catch prompt attacks",
      "Hide personal data and secrets in replies",
    ]);
    const readOnly = { ...STRUCTURE, tools: STRUCTURE.tools.filter((t) => t.risk !== "high") };
    expect(suggestGuardrails(readOnly).map((g) => g.id)).toEqual(["prompt-attacks", "hide-personal-data"]);
  });
});

describe("onboarding session", () => {
  it("rejects garbage and starts fresh", () => {
    expect(parseSession("not json")).toEqual(EMPTY_SESSION);
    expect(parseSession({ state: { currentStep: "nope" } })).toEqual(EMPTY_SESSION);
  });

  it("starts the connect clock on the first poll and remembers runs", () => {
    const { session } = pollStructure(EMPTY_SESSION, 1_000);
    expect(session.connectStartedAt).toBe(1_000);
    expect(pollStructure(session, 9_000).session.connectStartedAt).toBe(1_000);
    expect(startRun(session, "before", 5).session.runs.before).toBe("run-before-5");
  });
});

describe("onboarding_on_signup flag", () => {
  it("is off by default and only on for exactly '1'", () => {
    expect(flagOn("onboarding_on_signup", {})).toBe(false);
    expect(flagOn("onboarding_on_signup", { AGENTFOX_FLAG_ONBOARDING_ON_SIGNUP: "true" })).toBe(false);
    expect(flagOn("onboarding_on_signup", { AGENTFOX_FLAG_ONBOARDING_ON_SIGNUP: "1" })).toBe(true);
  });
});
