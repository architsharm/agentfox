import { describe, expect, it } from "vitest";

import { grantPrincipalKind } from "./entitlement";

describe("grantPrincipalKind", () => {
  it("an email address is a person, not a group", () => {
    expect(grantPrincipalKind("alice@yourcompany.com")).toBe("subject");
  });

  it("a bare name is a team", () => {
    expect(grantPrincipalKind("support-team")).toBe("group");
  });

  it("an explicit choice wins over the guess", () => {
    expect(grantPrincipalKind("svc-billing", "subject")).toBe("subject");
    expect(grantPrincipalKind("ops@lists.example.com", "group")).toBe("group");
  });

  it("'auto' and an empty value fall back to the guess", () => {
    expect(grantPrincipalKind("bob@example.com", "auto")).toBe("subject");
    expect(grantPrincipalKind("bob@example.com", "")).toBe("subject");
  });
});
