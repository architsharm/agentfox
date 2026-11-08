import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, playgroundCall } from "@/lib/marketing/playground";

afterEach(() => {
  vi.unstubAllGlobals();
});

/** A gateway that accepts the connection and never answers. */
function hangingFetch() {
  return vi.fn(
    (_url: string, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(init.signal!.reason));
      }),
  );
}

describe("playgroundCall", () => {
  it("gives up on a gateway that never answers instead of waiting forever", async () => {
    vi.stubGlobal("fetch", hangingFetch());
    const call = playgroundCall("http://gw", "/api/playground/sessions", { method: "POST" }, 50);
    // Not an ApiError, so the page shows its "could not be reached" message
    // and the button to start a new sandbox.
    await expect(call).rejects.not.toBeInstanceOf(ApiError);
    await expect(call).rejects.toThrow();
  });

  it("carries the gateway's own sentence on an error response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "Too many sandboxes." }), { status: 429 })),
    );
    const err = await playgroundCall("http://gw", "/api/playground/sessions").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(429);
    expect(err.message).toBe("Too many sandboxes.");
  });

  it("returns the body of a successful response", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ session_id: "pg_1" }), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(playgroundCall("http://gw", "/api/playground/sessions")).resolves.toEqual({
      session_id: "pg_1",
    });
    expect(fetchMock).toHaveBeenCalledWith("http://gw/api/playground/sessions", expect.anything());
  });
});
