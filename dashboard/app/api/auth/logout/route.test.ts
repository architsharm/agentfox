import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Sign Out used to delete the cookie and nothing else, so the token it carried —
 * a 365-day GitHub-login credential — stayed valid at the gateway. These pin that
 * the presented token is revoked, and that a gateway failure still signs out.
 */

const { POST } = await import("./route");

function logout(cookie?: string) {
  return new NextRequest("http://localhost:3000/api/auth/logout", {
    method: "POST",
    headers: cookie ? { Cookie: `agentfox_session=${cookie}` } : {},
  });
}

describe("sign out", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn(async () => new Response('{"revoked":true}', { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => vi.unstubAllGlobals());

  it("revokes the session's token at the gateway and clears the cookie", async () => {
    const res = await POST(logout("nom_api_session123"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/auth\/logout$/);
    expect(init.method).toBe("POST");
    expect(init.headers.Authorization).toBe("Bearer nom_api_session123");
    expect(res.headers.get("location")).toMatch(/\/login$/);
    expect(res.headers.get("set-cookie") || "").toMatch(/agentfox_session=;/);
  });

  it("still signs the browser out when the gateway is unreachable", async () => {
    fetchMock.mockRejectedValueOnce(new Error("ECONNREFUSED"));
    const res = await POST(logout("nom_api_session123"));
    expect(res.headers.get("set-cookie") || "").toMatch(/agentfox_session=;/);
  });

  it("makes no gateway call without a session", async () => {
    await POST(logout());
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
