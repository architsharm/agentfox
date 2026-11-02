import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/** ConditionFields reads `/api/tools`; this route did not exist and the request 404'd. */

const cookiesGetMock = vi.fn();
vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({ get: cookiesGetMock })),
}));

const { GET } = await import("./route");

describe("tools proxy", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    cookiesGetMock.mockReturnValue({ value: "nom_api_test" });
    fetchMock = vi.fn(async () => new Response(JSON.stringify({ tools: [{ key: "refunds.issue" }] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    cookiesGetMock.mockReset();
  });

  it("GETs the gateway's tool list and returns it", async () => {
    const res = await GET();
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/api\/tools$/);
    expect(fetchMock.mock.calls[0][1].method).toBe("GET");
    expect(await res.json()).toEqual({ tools: [{ key: "refunds.issue" }] });
  });
});
