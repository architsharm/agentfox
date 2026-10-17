import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { requestOrigin } from "./origin";

describe("requestOrigin", () => {
  it("keeps the host the browser used, not the server's own name", () => {
    const req = new NextRequest("http://localhost:3019/api/auth/token", { headers: { host: "127.0.0.1:3019" } });
    expect(requestOrigin(req)).toBe("http://127.0.0.1:3019");
  });
  it("uses the public host behind a proxy", () => {
    const req = new NextRequest("http://internal:3000/x", {
      headers: { host: "internal:3000", "x-forwarded-host": "useagentfox.com", "x-forwarded-proto": "https" },
    });
    expect(requestOrigin(req)).toBe("https://useagentfox.com");
  });
});
