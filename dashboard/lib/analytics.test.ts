import { describe, expect, it } from "vitest";

import { reported } from "./analytics";

describe("reported", () => {
  it("reports public pages and the welcome page only", () => {
    expect(reported("/")).toBe(true);
    expect(reported("/blog/ai-agent-audit-trail")).toBe(true);
    expect(reported("/login")).toBe(true);
    expect(reported("/app/welcome")).toBe(true);
  });
  it("never reports a signed-in product page", () => {
    expect(reported("/app")).toBe(false);
    expect(reported("/app/agents/support-bot")).toBe(false);
    expect(reported("/app/welcome/x")).toBe(false);
  });
});
