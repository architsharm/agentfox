import { describe, expect, it } from "vitest";
import {
  filterTools,
  groupSummary,
  groupTools,
  permissionCall,
  prefixOf,
  ruleChange,
  ruleSetting,
  stageTone,
  toolTone,
  type MapRule,
  type MapTool,
} from "./guardrailMap";

const IMPACTS = ["read", "write", "high_impact", "irreversible", null];
const PERMS = ["allowed", "ask", "not_granted"] as const;

function tool(i: number, extra: Partial<MapTool> = {}): MapTool {
  const server = ["github", "slack", "crm", "billing", "files"][i % 5];
  return {
    key: i % 7 === 0 ? `tool_${i}` : `mcp__${server}__op_${i}`,
    name: "",
    impact: IMPACTS[i % 5],
    permission: PERMS[i % 3],
    limits: {},
    rules: [],
    ladders: [],
    stats: i % 4 === 0 ? { total: 3, blocked: 1 } : {},
    sources: i % 4 === 0 ? ["seen"] : i % 3 === 0 ? ["code"] : ["granted"],
    grant: null,
    ...extra,
  };
}

const rule = (r: Partial<MapRule>): MapRule => ({ id: "r", description: "", effect: "block", mode: "enforce", level: "org", message: "", hits: 0, ...r });

describe("grouping 150 tools", () => {
  const tools = Array.from({ length: 150 }, (_, i) => tool(i));

  it("puts every tool in exactly one group, for every grouping", () => {
    for (const by of ["impact", "permission", "source", "prefix"] as const) {
      const groups = groupTools(tools, by);
      expect(groups.reduce((n, g) => n + g.tools.length, 0)).toBe(150);
      expect(new Set(groups.flatMap((g) => g.tools.map((t) => t.key))).size).toBe(150);
    }
  });

  it("keeps the number of groups small enough to draw", () => {
    expect(groupTools(tools, "impact").map((g) => g.label)).toEqual(["Irreversible", "High impact", "Writes", "Read only", "Risk not set"]);
    expect(groupTools(tools, "permission")).toHaveLength(3);
    const prefixes = groupTools(tools, "prefix");
    expect(prefixes.at(-1)?.label).toBe("No prefix");
    expect(prefixes.length).toBe(6);
  });

  it("searches and filters", () => {
    expect(filterTools(tools, "GITHUB", "all").every((t) => t.key.includes("github"))).toBe(true);
    expect(filterTools(tools, "", "not_granted").every((t) => t.permission === "not_granted")).toBe(true);
    expect(filterTools(tools, "", "called").every((t) => t.stats.total)).toBe(true);
  });

  it("summarises a group", () => {
    const s = groupSummary(tools.slice(0, 6));
    expect(s.allowed + s.ask + s.denied).toBe(6);
    expect(s.calls).toBe(6);
  });
});

describe("prefixOf", () => {
  it("reads MCP servers and dotted names", () => {
    expect(prefixOf("mcp__github__create_issue")).toBe("github");
    expect(prefixOf("github__create_issue")).toBe("github");
    expect(prefixOf("crm.lookup")).toBe("crm");
    expect(prefixOf("lookup")).toBe("");
  });
});

describe("tones", () => {
  it("tells enforcing, watching and nothing apart", () => {
    expect(stageTone([rule({})])).toBe("on");
    expect(stageTone([rule({ mode: "observe" })])).toBe("watch");
    expect(stageTone([rule({ effect: "allow" })])).toBe("watch");
    expect(stageTone([], ["pii"])).toBe("watch");
    expect(stageTone([])).toBe("off");
    expect(stageTone([rule({ enabled: false })])).toBe("off");
    // A watching agent copy beside an enforcing workspace one still enforces.
    expect(stageTone([rule({ mode: "observe", also: [{ effect: "redact", mode: "enforce" }] })])).toBe("on");
    expect(toolTone(tool(1, { ladders: [{ key: "l", name: "l", mode: "observe", field: null }] }))).toBe("watch");
    expect(toolTone(tool(1))).toBe("off");
  });
});

describe("changes", () => {
  it("maps the rule control to a per-agent change", () => {
    expect(ruleChange("a", "off")).toEqual({ agents: ["a"], enabled: false });
    expect(ruleChange("a", "escalate")).toEqual({ agents: ["a"], enabled: true, effect: "escalate" });
    expect(ruleSetting(rule({ effect: "redact" }))).toBeNull();
    expect(ruleSetting(rule({ enabled: false }))).toBe("off");
  });

  it("maps the access control to grants", () => {
    const own = tool(1, { key: "crm.lookup", limits: { id: { max: 3 } }, grant: { id: "g1", key: "crm.lookup", max_taint: "none", actions: ["read"] } });
    expect(permissionCall("a", own, "not_granted")).toEqual({ url: "/api/agents/a/access/g1", method: "DELETE" });
    expect(permissionCall("a", own, "ask")?.body).toEqual({ tool_key: "crm.lookup", requires_approval: true, max_taint: "none", constraints: { id: { max: 3 } }, actions: ["read"] });
    const viaPattern = tool(1, { key: "crm.lookup", grant: { id: "g2", key: "crm.*", max_taint: "user", actions: ["*"] } });
    expect(permissionCall("a", viaPattern, "not_granted")).toBeNull();
    expect(permissionCall("a", viaPattern, "allowed")?.body).toMatchObject({ tool_key: "crm.lookup", requires_approval: false, constraints: {} });
  });
});
