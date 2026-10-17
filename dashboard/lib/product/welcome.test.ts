import { describe, expect, it } from "vitest";

import { INSTALL_SPEC, scanRows, sortRepos, upCommand } from "./welcome";

describe("sortRepos", () => {
  it("offers the most recently updated repository first", () => {
    const repos = [
      { full_name: "a/old", updated_at: "2026-01-01T00:00:00Z" },
      { full_name: "a/new", updated_at: "2026-10-01T00:00:00Z" },
      { full_name: "a/mid", updated_at: "2026-05-01T00:00:00Z" },
    ].map((r) => ({ ...r, private: false, default_branch: "main", description: "" }));
    expect(sortRepos(repos).map((r) => r.full_name)).toEqual(["a/new", "a/mid", "a/old"]);
  });
});

describe("upCommand", () => {
  const base = { gateway: "https://api.example.com", token: "af_123" };

  it("answers every question up would ask", () => {
    const cmd = upCommand({ ...base, siteUrl: "https://agentfox.internal.example" });
    expect(cmd).toContain("AGENTFOX_API_TOKEN=af_123");
    expect(cmd).toContain(`uvx --from ${INSTALL_SPEC}`);
    expect(cmd).toContain("--target self-hosted --api-url https://api.example.com --mode observe --yes");
  });

  it("targets cloud only on the hosted product", () => {
    expect(upCommand({ ...base, siteUrl: "https://useagentfox.com" })).toContain("--target cloud");
    expect(upCommand({ ...base, siteUrl: "not a url" })).toContain("--target self-hosted");
  });
});

describe("scanRows", () => {
  it("says nothing it was not told", () => {
    expect(scanRows({})).toEqual([]);
  });

  it("marks trifectas and flagged skills as the rows to act on", () => {
    const rows = scanRows({
      frameworks: ["OpenAI SDK"],
      highlights: {
        model_calls: 3,
        ungoverned_model_calls: 2,
        tools: 0,
        mcp_servers: ["github"],
        trifectas: [{ file: ".mcp.json", detail: "…" }],
        skills: 2,
        skill_issues: [
          { skill: "evil", path: "x", type: "skill_poisoning", severity: "high" },
          { skill: "evil", path: "x", type: "skill_dangerous_command", severity: "high" },
        ],
      },
    });
    const byLabel = Object.fromEntries(rows.map((r) => [r.label, r]));
    expect(byLabel["Model calls"]).toMatchObject({ value: "3 (2 ungoverned)", tone: "warn" });
    expect(byLabel["Lethal trifectas"].tone).toBe("bad");
    expect(byLabel["Skills"].value).toBe("2 (1 flagged: planted instructions or risky commands)");
    expect(byLabel["Tools"]).toBeUndefined();
    expect(byLabel["Built on"].value).toBe("OpenAI SDK");
  });
});
