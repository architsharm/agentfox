import { describe, expect, it } from "vitest";

import { TEMPLATES, findTemplate, toolRows } from "@/lib/marketing/templates";

describe("the /templates data", () => {
  it("reads each tool's impact and grant from the policy lines", () => {
    const rows = toolRows(findTemplate("support-agent").policy);
    expect(rows.find((r) => r.tool === "send_email")).toEqual({ tool: "send_email", impact: "high_impact", grant: "Granted" });
    expect(rows.find((r) => r.tool === "issue_credit")?.grant).toBe("Granted, every call held for a person, limit amount:lte=50");
  });

  it("lists every declared tool once, and only declared tools", () => {
    for (const t of TEMPLATES) {
      const declared = t.policy.filter((l) => l.startsWith("agentfox declare tool ")).length;
      expect(toolRows(t.policy)).toHaveLength(declared);
      expect(toolRows(t.policy).every((r) => r.grant.startsWith("Granted")), t.slug).toBe(true);
    }
  });
});
