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

  it("finds test suites, controls and evidence packs", () => {
    const more = buildIndex({
      suites: [{ key: "refunds", name: "Refund regressions" }],
      controls: [{ key: "NOM-AUD-02", title: "Tamper-evident audit log" }],
      evidence: [{ id: "evp_1", scope: { agents: ["*"], period_from: "2026-10-01T00:00:00Z", period_to: "2026-11-01T00:00:00Z" } }],
    });
    expect(match(more, "refund")[0]).toMatchObject({ group: "Test suite", href: "/app/evals/refunds" });
    expect(match(more, "NOM-AUD-02")[0]).toMatchObject({ group: "Control", href: "/app/compliance/controls/NOM-AUD-02" });
    expect(match(more, "evidence")[0]).toMatchObject({ label: "Evidence pack: all agents", href: "/app/reports?tab=evidence" });
  });
});
