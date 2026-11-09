import { describe, expect, it } from "vitest";

import { snippetsFor } from "./snippets";

describe("python snippet", () => {
  const snippets = snippetsFor("python", "https://gw.example.com", "billing-bot");

  it("leads with agentfox.auto(), the path the docs teach", () => {
    const first = snippets.findIndex((s) => s.code.includes("agentfox.auto("));
    const manual = snippets.findIndex((s) => s.code.includes("from agentfox import AgentFox"));
    expect(first).toBeGreaterThan(-1);
    expect(snippets[first].code).toContain('agentfox.auto("billing-bot")');
    expect(manual === -1 || manual > first).toBe(true);
  });

  it("uses the same install line as the docs and points at this gateway", () => {
    expect(snippets[0].code).toBe("pip install -U agentfox");
    expect(snippets.map((s) => s.code).join("\n")).toContain("AGENTFOX_URL=https://gw.example.com");
  });

  it("puts no real key in the snippet", () => {
    expect(snippets.map((s) => s.code).join("\n")).not.toMatch(/nom_api_[A-Za-z0-9]/);
  });
});
