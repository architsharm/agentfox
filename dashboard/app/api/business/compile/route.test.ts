import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The Describe-a-rule box sends the agent it is scoped to, and the gateway uses it
 * to resolve tool names against that agent's declared tools. This handler used to
 * forward `text` alone, so the agent never arrived.
 */

const cookiesGetMock = vi.fn();
vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({ get: cookiesGetMock })),
}));

const { POST } = await import("./route");

const post = (body: unknown) =>
  new NextRequest("http://localhost:3000/api/business/compile", {
    method: "POST",
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json" },
  });

describe("business compile proxy", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    cookiesGetMock.mockReturnValue({ value: "nom_api_test" });
    fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    cookiesGetMock.mockReset();
  });

  it("forwards the agent with the text", async () => {
    await POST(post({ text: "never refund over $500", agent: "support-bot" }));
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/api\/business\/compile$/);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ text: "never refund over $500", agent: "support-bot" });
  });

  it("leaves agent out when there is none", async () => {
    await POST(post({ text: "never refund over $500" }));
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ text: "never refund over $500" });
  });
});
