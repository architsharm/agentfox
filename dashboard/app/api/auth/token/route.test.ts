import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Token sign-in is the way into a self-hosted dashboard that has no GitHub OAuth
 * app. The token must be checked against the gateway before it becomes a session,
 * and a cross-site form must not be able to sign the browser in.
 */

const { POST } = await import("./route");

function signIn(token: string, origin = "http://localhost:3000") {
  return new NextRequest("http://localhost:3000/api/auth/token", {
    method: "POST",
    body: new URLSearchParams([["token", token]]),
    headers: { "Content-Type": "application/x-www-form-urlencoded", Origin: origin },
  });
}

describe("sign in with an API token", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => vi.unstubAllGlobals());

  it("sets the session cookie for a token the gateway accepts", async () => {
    const res = await POST(signIn("nom_api_good"));
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/me$/);
    expect(init.headers.Authorization).toBe("Bearer nom_api_good");
    expect(res.headers.get("location")).toMatch(/\/app\/start$/);
    expect(res.headers.get("set-cookie") || "").toMatch(/agentfox_session=nom_api_good/);
  });

  it("refuses a token the gateway rejects", async () => {
    fetchMock.mockResolvedValueOnce(new Response("{}", { status: 401 }));
    const res = await POST(signIn("nom_api_bad"));
    expect(res.headers.get("location")).toMatch(/\/login\?error=/);
    expect(res.headers.get("set-cookie")).toBeNull();
  });

  it("refuses something that is not an operator token without calling the gateway", async () => {
    const res = await POST(signIn("nom_agt_agentkey"));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(res.headers.get("location")).toMatch(/\/login\?error=/);
  });

  it("refuses a cross-site form post", async () => {
    const res = await POST(signIn("nom_api_good", "https://evil.example"));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(res.headers.get("set-cookie")).toBeNull();
  });
});
