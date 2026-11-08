import { describe, expect, it } from "vitest";

import { buildIndex, match } from "./searchIndex";

const index = buildIndex({
  agents: [{ slug: "payments-ops", name: "Payments Operations Agent" }],
  tools: [{ key: "payments.transfer", name: "Transfer money" }],
  policies: [
    { live_compiled: { rules: [{ id: "injection.direct", description: "Prompt injection in user input" }] } },
    { compiled: { rules: [{ id: "injection.direct", description: "dup" }, { id: "custom.words", description: "Blocked words" }] } },
  ],
  findings: [{ id: "fnd_1", title: "Refund over limit", severity: "high", agent_slug: "support" }],
});

describe("Cmd-K index", () => {
  it("indexes agents, tools, rules (once each) and issues with where they go", () => {
    expect(index.map((i) => i.group)).toEqual(["Agent", "Tool", "Rule", "Rule", "Issue"]);
    expect(index[0].href).toBe("/app/projects/payments-ops");
    expect(index[2].href).toBe("/app/policies/rules/injection.direct");
    expect(index[4]).toMatchObject({ href: "/app/findings/fnd_1", sub: "high · support" });
  });

  it("matches names, ids and every word, label prefixes first", () => {
    expect(match(index, "transfer").map((i) => i.group)).toEqual(["Tool"]);
    expect(match(index, "payments").map((i) => i.label)).toEqual(["Payments Operations Agent", "Transfer money"]);
    expect(match(index, "refund high").map((i) => i.group)).toEqual(["Issue"]);
    expect(match(index, "injection.direct")[0].group).toBe("Rule");
    expect(match(index, "nothing like this")).toEqual([]);
  });
});
