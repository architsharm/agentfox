import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * lib/product/proxy.ts is the auth/mutation boundary every write route in the dashboard
 * goes through (~40+ route.ts files call one of its exported wrappers). The one
 * property that actually matters here is the one the module's own docstring
 * states explicitly: a caller with no real session gets a clean "not signed in"
 * instead of a silently-misattributed write — which means the single most
 * important thing to prove is that an unauthenticated request never reaches the
 * gateway at all, not just that it gets an error back.
 */

const cookiesGetMock = vi.fn();
vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({ get: cookiesGetMock })),
}));

const { proxyReviewAction, proxyJson } = await import("./proxy");

function withToken(token: string | undefined) {
  cookiesGetMock.mockReturnValue(token === undefined ? undefined : { value: token });
}

function req(path = "/app/agents/support-triage") {
  return new NextRequest(`http://localhost:3000${path}`);
}

describe("proxy auth/mutation boundary", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    cookiesGetMock.mockReset();
  });

  describe("redirect-shaped calls (proxyReviewAction)", () => {
    it("an unauthenticated caller is redirected with an error and the gateway is never called", async () => {
      withToken(undefined);

      const res = await proxyReviewAction(req(), "/api/agents/x/approve", "/app/agents");

      expect(fetchMock).not.toHaveBeenCalled();
      expect(res.status).toBe(307); // NextResponse.redirect default
      const location = new URL(res.headers.get("location")!);
      expect(location.pathname).toBe("/app/agents");
      expect(location.searchParams.get("review_error")).toBe("not signed in");
    });

    it("an authenticated success redirects clean, with the gateway called with a bearer token", async () => {
      withToken("real-session-token");
      fetchMock.mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));

      const res = await proxyReviewAction(req(), "/api/agents/x/approve", "/app/agents", {
        successNotice: "Agent approved.",
      });

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, init] = fetchMock.mock.calls[0];
      expect(String(url)).toContain("/api/agents/x/approve");
      expect(init.headers.Authorization).toBe("Bearer real-session-token");

      const location = new URL(res.headers.get("location")!);
      expect(location.searchParams.get("review_error")).toBeNull();
      expect(location.searchParams.get("review_notice")).toBe("Agent approved.");
    });

    it("a non-ok gateway response surfaces its detail as the error, not a generic failure", async () => {
      withToken("real-session-token");
      fetchMock.mockResolvedValue(
        new Response(JSON.stringify({ detail: "agent already approved" }), { status: 409 }),
      );

      const res = await proxyReviewAction(req(), "/api/agents/x/approve", "/app/agents");

      const location = new URL(res.headers.get("location")!);
      expect(location.searchParams.get("review_error")).toBe("agent already approved");
    });

    it("a network exception is caught and surfaced as an error redirect, not an unhandled rejection", async () => {
      withToken("real-session-token");
      fetchMock.mockRejectedValue(new Error("fetch failed: ECONNREFUSED"));

      const res = await proxyReviewAction(req(), "/api/agents/x/approve", "/app/agents");

      const location = new URL(res.headers.get("location")!);
      expect(location.searchParams.get("review_error")).toContain("ECONNREFUSED");
    });

    it("honours a custom errorParam instead of the review_error default", async () => {
      withToken(undefined);

      const res = await proxyReviewAction(req(), "/api/start/scan", "/app/start", {
        errorParam: "scan_error",
      });

      const location = new URL(res.headers.get("location")!);
      expect(location.searchParams.get("scan_error")).toBe("not signed in");
      expect(location.searchParams.get("review_error")).toBeNull();
    });
  });

  describe("JSON-shaped calls (proxyJson, used by interactive client components)", () => {
    it("an unauthenticated caller gets a 401 body and the gateway is never called", async () => {
      withToken(undefined);

      const res = await proxyJson("/api/policies", "POST", { body: "key: x" });

      expect(fetchMock).not.toHaveBeenCalled();
      expect(res.status).toBe(401);
      const json = await res.json();
      expect(json.detail).toBe("not signed in");
    });

    it("an authenticated call forwards the gateway's status and body verbatim", async () => {
      withToken("real-session-token");
      fetchMock.mockResolvedValue(
        new Response(JSON.stringify({ id: "pol_123" }), { status: 201 }),
      );

      const res = await proxyJson("/api/policies", "POST", { body: "key: x" });

      expect(res.status).toBe(201);
      const json = await res.json();
      expect(json.id).toBe("pol_123");
      const [, init] = fetchMock.mock.calls[0];
      expect(JSON.parse(init.body)).toEqual({ body: "key: x" });
    });
  });
});
