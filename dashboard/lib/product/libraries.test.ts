import { describe, expect, it } from "vitest";
import { checksLabel, doesLabel, groupApplied, libraryPath, libraryState, simulationSummary, whereOn, wouldDoLabel } from "./libraries";

describe("checksLabel", () => {
  it("names each surface once, in people's words", () => {
    expect(checksLabel({ surfaces: ["input", "output"] })).toBe("User messages, Replies");
    expect(checksLabel({ surfaces: ["tool_call", "tool_args"] })).toBe("Tool calls");
  });

  it("puts a tool rule with no surface on tool calls, else on every check", () => {
    expect(checksLabel({ surfaces: [], tool: "db.*" })).toBe("Tool calls");
    expect(checksLabel({ surfaces: [] })).toBe("Every check");
  });
});

describe("doesLabel", () => {
  it("says block, hide and ask a person", () => {
    expect(doesLabel("block")).toBe("Block");
    expect(doesLabel("redact")).toBe("Hide");
    expect(doesLabel("escalate")).toBe("Ask a person");
    expect(doesLabel("something-new")).toBe("something-new");
  });
});

describe("libraryState", () => {
  const base = { agents: [], blocking: false, workspace: false };

  it("is not applied, watching on some agents, or blocking on all", () => {
    expect(libraryState(base, 3)).toEqual({ text: "Not applied", tone: "" });
    expect(libraryState({ ...base, agents: ["a"] }, 3)).toEqual({ text: "On 1 of 3 agents · watching", tone: "pol-watch" });
    expect(libraryState({ ...base, agents: ["a", "b", "c"], blocking: true, outdated: true }, 3).text).toBe("On all 3 agents · blocking · update available");
    expect(libraryState({ ...base, agents: ["a"] }, 1).text).toBe("On the agent · watching");
  });

  it("says when it was applied workspace-wide", () => {
    expect(libraryState({ ...base, workspace: true, blocking: true }, 2)).toEqual({ text: "On every agent (workspace) · blocking", tone: "pol-on" });
  });
});

describe("simulationSummary", () => {
  it("counts what would have happened, or says there was nothing to replay", () => {
    expect(simulationSummary({ replayed: 140, blocked: 3, held: 1, hidden: 2, since_days: 30 })).toBe(
      "Last 30 days: would have blocked 3, asked a person about 1 and hidden data in 2 of 140 checks.",
    );
    expect(simulationSummary({ replayed: 9, blocked: 0, held: 0, hidden: 0, since_days: 7 })).toBe("Last 7 days: would have blocked 0 of 9 checks.");
    expect(simulationSummary({ replayed: 0, blocked: 0, held: 0, hidden: 0, since_days: 30 })).toMatch(/^No traffic in the last 30 days/);
  });
});

describe("whereOn / libraryPath", () => {
  it("words the agents and keeps a library id's slash", () => {
    expect(whereOn(2, 2)).toBe("all 2 agents");
    expect(libraryPath("payments/refunds")).toBe("payments/refunds");
    expect(libraryPath("a b")).toBe("a%20b");
  });
});

describe("a watching library's rules", () => {
  it("say what they would do", () => {
    expect(wouldDoLabel("block")).toBe("Would block");
    expect(wouldDoLabel("escalate")).toBe("Would ask a person");
    expect(wouldDoLabel("tokenize")).toBe("Would hide");
    expect(wouldDoLabel("allow")).toBe("Allow");
  });
});

describe("applied rules by library", () => {
  const row = (id: string, lib: string, mode = "enforce", effect = "block") => ({ id, effect, mode, libraries: [lib] });

  it("groups by library, acting groups and rules first", () => {
    const groups = groupApplied([
      row("a", "EU AI Act", "observe"),
      row("b", "Tool containment", "observe", "escalate"),
      row("c", "Tool containment"),
      row("d", "EU AI Act", "observe"),
      row("e", "Baseline", "observe"),
    ]);
    expect(groups.map((g) => g.library)).toEqual(["Tool containment", "EU AI Act", "Baseline"]);
    expect(groups[0].rules.map((r) => r.id)).toEqual(["c", "b"]);
    expect(groups.map((g) => g.blocking)).toEqual([1, 0, 0]);
  });

  it("puts a rule with no library under Other rules, and an allow rule never counts as acting", () => {
    const [g] = groupApplied([{ id: "x", effect: "allow", mode: "enforce", libraries: [] }]);
    expect(g).toEqual({ library: "Other rules", rules: [{ id: "x", effect: "allow", mode: "enforce", libraries: [] }], blocking: 0 });
  });
});
