import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * `safeApi` hands a page its fallback when a call fails, which is right for a gateway
 * that is down and wrong for a session it no longer accepts: the Approvals page then
 * read "Nothing is waiting for you" over approvals that existed.
 */

const cookiesGetMock = vi.fn();
vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({ get: cookiesGetMock })),
}));
const redirectMock = vi.fn((to: string) => {
  throw new Error(`NEXT_REDIRECT ${to}`);
});
vi.mock("next/navigation", () => ({ redirect: (to: string) => redirectMock(to) }));

const { safeApi } = await import("./api");

describe("safeApi", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    redirectMock.mockClear();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("sends a rejected session to sign in again instead of showing empty data", async () => {
    cookiesGetMock.mockReturnValue({ value: "nom_api_revoked" });
    fetchMock.mockResolvedValue(new Response("not signed in", { status: 401 }));
    await expect(safeApi("/api/approvals?status=pending", { approvals: [] })).rejects.toThrow(
      "NEXT_REDIRECT /login?session=expired",
    );
  });

  it("still falls back on other failures", async () => {
    cookiesGetMock.mockReturnValue({ value: "nom_api_ok" });
    fetchMock.mockResolvedValue(new Response("forbidden", { status: 403 }));
    await expect(safeApi("/api/x", { ok: false })).resolves.toEqual({ ok: false });
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    await expect(safeApi("/api/x", { ok: false })).resolves.toEqual({ ok: false });
    expect(redirectMock).not.toHaveBeenCalled();
  });

  it("does not redirect without a session cookie", async () => {
    cookiesGetMock.mockReturnValue(undefined);
    fetchMock.mockResolvedValue(new Response("no", { status: 401 }));
    await expect(safeApi("/api/x", [])).resolves.toEqual([]);
  });
});
