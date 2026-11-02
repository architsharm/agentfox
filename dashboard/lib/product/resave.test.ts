import { describe, expect, it } from "vitest";
import { conditionFrom, conditionSpec } from "@/components/product/policies/ConditionFields";
import { bandsForSave, canCheckFirst, grantPayload, keptRuleFields, keptWithin } from "./resave";

describe("re-saving what the gateway stores whole", () => {
  it("an edit to a narrowed grant sends its actions back", () => {
    const cap = { tool_key: "crm.lookup", actions: ["read"], requires_approval: false, max_taint: "user", constraints: {} };
    expect(grantPayload(cap, { requires_approval: true })).toEqual({ ...cap, requires_approval: true });
  });

  it("a grant listed without actions leaves them to the gateway", () => {
    const body = grantPayload({ tool_key: "x", requires_approval: false, max_taint: "user", constraints: {} }, {});
    expect("actions" in body).toBe(false);
  });

  it("a ladder keeps each band's check and label, ordered with the open band last", () => {
    const verify = { check: "risk.refund_check" };
    const out = bandsForSave([
      { upto: null, outcome: "block", approver_role: "", reason: "" },
      { upto: 500, outcome: "verify", verify, label: "Mid", approver_role: "", reason: "" },
      { upto: 100, outcome: "allow", label: "Small", approver_role: "", reason: "" },
    ]);
    expect(out).toEqual([
      { outcome: "allow", label: "Small", upto: 100 },
      { outcome: "verify", label: "Mid", upto: 500, verify },
      { outcome: "block" },
    ]);
  });

  it("a band moved off check-first or ask-a-person drops what only those use", () => {
    const [b] = bandsForSave([{ upto: 10, outcome: "allow", verify: { check: "c" }, approver_role: "manager" }]);
    expect(b).toEqual({ outcome: "allow", upto: 10 });
  });

  it("check first is only offered on a band that has a check", () => {
    expect(canCheckFirst({ upto: 1, outcome: "allow" })).toBe(false);
    expect(canCheckFirst({ upto: 1, outcome: "allow", verify: { check: "c" } })).toBe(true);
  });

  it("an edited custom rule keeps its case, its on/off, and its sequence window", () => {
    expect(keptRuleFields({ case_sensitive: true, enabled: false })).toEqual({ case_sensitive: true, enabled: false });
    expect(keptRuleFields(undefined)).toEqual({});
    expect(keptWithin({ sequence: { within: "trace" } })).toEqual({ within: "trace" });
    expect(keptWithin(undefined)).toEqual({});
  });

  it("a value check keeps its case sensitivity through the form", () => {
    const spec = { surface: "output", field: "", measure: "value", operator: "contains", value: "ACME", case_sensitive: true };
    expect(conditionSpec(conditionFrom(spec)).case_sensitive).toBe(true);
  });
});
