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

  it("exchanges an accepted key for a session token of its own, so signing out never revokes the key", async () => {
    fetchMock
      .mockResolvedValueOnce(new Response("{}", { status: 200 }))
      .mockResolvedValueOnce(new Response('{"token":"nom_api_session"}', { status: 201 }));
    const res = await POST(signIn("nom_api_good"));
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/me$/);
    expect(init.headers.Authorization).toBe("Bearer nom_api_good");
    const [mint, mintInit] = fetchMock.mock.calls[1];
    expect(String(mint)).toMatch(/\/api\/tokens$/);
    expect(mintInit.headers.Authorization).toBe("Bearer nom_api_good");
    // The one first screen: Agents (/app), as after GitHub or Google.
    expect(res.headers.get("location")).toMatch(/\/app$/);
    const cookies = res.headers.get("set-cookie") || "";
    expect(cookies).toMatch(/agentfox_session=nom_api_session/);
    expect(cookies).not.toMatch(/agentfox_session=nom_api_good/);
  });

  it("keeps the pasted key as the session, marked kept, when the gateway can't mint one", async () => {
    fetchMock
      .mockResolvedValueOnce(new Response("{}", { status: 200 }))
      .mockResolvedValueOnce(new Response("{}", { status: 404 }));
    const res = await POST(signIn("nom_api_good"));
    const cookies = res.headers.get("set-cookie") || "";
    expect(cookies).toMatch(/agentfox_session=nom_api_good/);
    expect(cookies).toMatch(/agentfox_session_kept=1/);
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
