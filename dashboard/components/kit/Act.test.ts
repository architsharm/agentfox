import { afterEach, describe, expect, it, vi } from "vitest";
import { NETWORK_ERROR, callJson } from "./Act";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("callJson", () => {
  it("turns a network failure into a sentence a person can act on", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(callJson("/api/x", "POST", {})).rejects.toThrow(NETWORK_ERROR);
  });

  it("never throws an empty message when the status text is blank (HTTP/2)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("not json", { status: 502, statusText: "" })));
    await expect(callJson("/api/x", "POST")).rejects.toThrow("Request failed (502). Try again.");
  });

  it("prefers the gateway's own detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Name is taken." }), { status: 409 })),
    );
    await expect(callJson("/api/x", "POST")).rejects.toThrow("Name is taken.");
  });

  it("returns the body on success", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: 1 }), { status: 200 })));
    await expect(callJson("/api/x", "GET")).resolves.toEqual({ ok: 1 });
  });
});
