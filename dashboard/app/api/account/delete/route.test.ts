import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * "Delete my account": the typed confirmation reaches the gateway, success clears
 * the session and lands on /login, and a refusal goes back to Settings with the
 * gateway's reason and the session intact.
 */

const { POST } = await import("./route");

function del(confirm: string) {
  return new NextRequest("http://localhost:3000/api/account/delete", {
    method: "POST",
    headers: {
      Cookie: "agentfox_session=nom_api_session123",
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({ confirm }),
  });
}

describe("delete my account", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn(async () => new Response('{"deleted":true,"rows":12}', { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => vi.unstubAllGlobals());

  it("sends the typed email, then signs the browser out", async () => {
    const res = await POST(del("ada@corp.example"));
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/account\/delete$/);
    expect(init.headers.Authorization).toBe("Bearer nom_api_session123");
    expect(JSON.parse(init.body)).toEqual({ confirm: "ada@corp.example" });
    expect(res.headers.get("location")).toMatch(/\/login\?deleted=1$/);
    expect(res.headers.get("set-cookie") || "").toMatch(/agentfox_session=;/);
  });

  it("goes back to Settings with the reason when the gateway refuses", async () => {
    fetchMock.mockResolvedValueOnce(new Response('{"detail":"A legal hold is active."}', { status: 409 }));
    const res = await POST(del("ada@corp.example"));
    const location = new URL(res.headers.get("location") || "");
    expect(location.pathname).toBe("/app/settings");
    expect(location.searchParams.get("review_error")).toBe("A legal hold is active.");
    expect(res.headers.get("set-cookie") || "").not.toMatch(/agentfox_session=;/);
  });
});
