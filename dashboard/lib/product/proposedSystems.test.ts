import { describe, expect, it } from "vitest";
import { drawnSubagents, linkActivity, parentLabel, relationLabel, type MapLink } from "./guardrailMap";
import { groupProposed, memberRelation, type ProposedAgent } from "./proposedSystems";

function agent(slug: string, children: [string, string][] = []): ProposedAgent {
  return { id: `id-${slug}`, slug, children: children.map(([s, relation]) => ({ slug: s, relation })) };
}

describe("groupProposed", () => {
  it("puts a system's agents under the one that hands them work", () => {
    const groups = groupProposed([
      agent("billing"),
      agent("triage", [
        ["billing", "handoff"],
        ["refunds", "as_tool"],
      ]),
      agent("refunds", [["ledger", "delegates"]]),
      agent("ledger"),
      agent("lonely"),
    ]);
    expect(groups.map((g) => g.root.slug)).toEqual(["triage", "lonely"]);
    expect(groups[0].members.map((m) => [m.agent.slug, m.depth, m.relation])).toEqual([
      ["triage", 0, null],
      ["billing", 1, "handoff"],
      ["refunds", 1, "as_tool"],
      ["ledger", 2, "delegates"],
    ]);
    expect(groups[1].members).toHaveLength(1);
  });

  it("lists an agent with two parents once, and cuts a cycle", () => {
    const groups = groupProposed([
      agent("a", [["b", "handoff"]]),
      agent("b", [["a", "handoff"]]),
      agent("crew", [
        ["x", "member"],
        ["y", "member"],
      ]),
      agent("x", [["y", "delegates"]]),
      agent("y"),
    ]);
    expect(groups.map((g) => g.members.map((m) => m.agent.slug))).toEqual([["crew", "x", "y"], ["a", "b"]]);
  });

  it("ignores children that are not proposals any more", () => {
    const groups = groupProposed([agent("triage", [["already-added", "handoff"]])]);
    expect(groups).toHaveLength(1);
    expect(groups[0].members).toHaveLength(1);
  });

  it("says how a member is reached", () => {
    expect(memberRelation("handoff")).toBe("Handed off to");
    expect(memberRelation(null)).toBe("");
    expect(memberRelation("delegates")).toBe("Delegated to");
  });
});

describe("sub-agents on the map", () => {
  const link = (slug: string, calls: number, extra: Partial<MapLink> = {}): MapLink => ({ slug, calls, ...extra });

  it("labels each relation in plain words", () => {
    expect(relationLabel("handoff")).toBe("Hands off to");
    expect(relationLabel("as_tool")).toBe("Used as a tool");
    expect(relationLabel("member", "CrewAI")).toBe("Crew member");
    expect(relationLabel("member", "AutoGen")).toBe("Team member");
    expect(relationLabel(null)).toBe("Delegates to");
    expect(parentLabel(null)).toBe("Called by");
  });

  it("tells a sub-agent known from code apart from one seen in traffic", () => {
    expect(linkActivity(link("a", 0, { declared: true }))).toBe("From code · no calls yet");
    expect(linkActivity(link("a", 1, { declared: true, seen: true }))).toBe("1 call");
    expect(linkActivity(link("a", 4, { seen: true }))).toBe("4 calls");
  });

  it("draws the busiest few and sums up the rest", () => {
    const subs = Array.from({ length: 9 }, (_, i) => link(`s${i}`, i));
    const { shown, rest } = drawnSubagents(subs, 6);
    expect(shown.map((s) => s.slug)).toEqual(["s8", "s7", "s6", "s5", "s4"]);
    expect(rest).toBe(4);
    expect(drawnSubagents(subs.slice(0, 6), 6)).toEqual({ shown: [...subs.slice(0, 6)].reverse(), rest: 0 });
  });
});
