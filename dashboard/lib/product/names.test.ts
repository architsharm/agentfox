import { describe, expect, it } from "vitest";

import { agentName, agentNames, withAgentNames } from "./names";

const names = agentNames([
  { slug: "payments-ops", name: "Payments Operations Agent" },
  { slug: "support", name: "Support" },
  { slug: "support-triage", name: "Support Triage Agent" },
  { slug: "same", name: "same" },
]);

describe("agent display names", () => {
  it("swaps slugs in gateway-written titles for names", () => {
    expect(withAgentNames("payments-ops tried to payments.transfer", names)).toBe(
      "Payments Operations Agent tried to payments.transfer",
    );
    expect(withAgentNames("Identity agent:support-triage is stale", names)).toBe("Identity Support Triage Agent is stale");
    expect(withAgentNames("Agent 'support' has no accountable owner", names)).toBe("Agent Support has no accountable owner");
  });

  it("does not touch a slug inside a longer word or a tool name", () => {
    expect(withAgentNames("support-triage-v2 called support.lookup", names)).toBe("support-triage-v2 called support.lookup");
  });

  it("falls back to the slug", () => {
    expect(agentName(names, "same")).toBe("same");
    expect(agentName(names, "unknown")).toBe("unknown");
    expect(agentName(names, "payments-ops")).toBe("Payments Operations Agent");
  });
});
