import { afterEach, describe, expect, it, vi } from "vitest";
import { httpApi } from "./api";
import { isFreshConnection, requestError, pendingPrompt, addLabel } from "./connect";

describe("creating a key", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("returns the key the server made", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ value: "afi_abc123", createdNow: false }), { status: 200 })),
    );
    await expect(httpApi.getKey()).resolves.toEqual({ value: "afi_abc123", createdNow: false });
    expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/onboarding/key", expect.objectContaining({ cache: "no-store" }));
  });

  it("says the server can't be reached when the gateway is down (502)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("Bad Gateway", { status: 502 })));
    await expect(httpApi.getKey()).rejects.toThrow("Can't reach the AgentFox server");
  });

  it("says the same when the request never gets an answer", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("fetch failed");
      }),
    );
    await expect(httpApi.getKey()).rejects.toThrow("Can't reach the AgentFox server");
  });

  it("asks to sign in again when the session has ended", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "unauthorized" }), { status: 401 })));
    await expect(httpApi.getKey()).rejects.toThrow("Sign in again");
  });
});

describe("requestError", () => {
  it("passes the server's own explanation through", () => {
    expect(requestError(409, { detail: "That project already exists." })).toBe("That project already exists.");
  });

  it("falls back to the status when the server gave no reason", () => {
    expect(requestError(500, {})).toBe("Something went wrong (500). Try again.");
  });
});

describe("isFreshConnection: has agentfox init just reported in?", () => {
  const live = (connectedAt: string | null, agents = 1) => ({
    connected: true,
    connectedAt,
    structure: { agents: Array.from({ length: agents }, () => ({})) },
  });

  it("waits until it knows what was there when the card opened", () => {
    expect(isFreshConnection(null, live("2026-10-20T10:00:00Z"))).toBe(false);
  });

  it("ignores a connection made before the card opened", () => {
    const before = { connected: true, at: "2026-10-20T10:00:00Z" };
    expect(isFreshConnection(before, live("2026-10-20T10:00:00Z"))).toBe(false);
  });

  it("accepts a connection made after the card opened", () => {
    const before = { connected: true, at: "2026-10-20T10:00:00Z" };
    expect(isFreshConnection(before, live("2026-10-20T10:05:00Z"))).toBe(true);
  });

  it("accepts the first connection ever", () => {
    expect(isFreshConnection({ connected: false, at: null }, live("2026-10-20T10:05:00Z"))).toBe(true);
  });

  it("never counts a connection that found no agents", () => {
    expect(isFreshConnection({ connected: false, at: null }, live("2026-10-20T10:05:00Z", 0))).toBe(false);
  });

  it("with no timestamp (older servers), only a first connection counts", () => {
    expect(isFreshConnection({ connected: false, at: null }, live(null))).toBe(true);
    expect(isFreshConnection({ connected: true, at: null }, live(null))).toBe(false);
  });
});

describe("pendingPrompt: the Add step stays until done or dismissed", () => {
  const live = {
    connected: true,
    connectedAt: "2026-11-09T10:00:00",
    structure: { project: "shop" },
    pending: [
      { slug: "a", name: "Planner" },
      { slug: "b", name: "Writer" },
    ],
  };
  it("asks while init's agents are still drafts", () => {
    const p = pendingPrompt(live, []);
    expect(p?.project).toBe("shop");
    expect(p?.agents.map((a) => a.slug)).toEqual(["a", "b"]);
    expect(addLabel(p!.agents)).toBe("Add 2 agents to AgentFox");
  });
  it("stops once they are added", () => {
    expect(pendingPrompt({ ...live, pending: [] }, [])).toBeNull();
  });
  it("stops once this report is dismissed, and asks again for a later init", () => {
    const key = pendingPrompt(live, [])!.key;
    expect(pendingPrompt(live, [key])).toBeNull();
    expect(pendingPrompt({ ...live, connectedAt: "2026-11-09T11:00:00" }, [key])).not.toBeNull();
    expect(pendingPrompt({ ...live, structure: { project: "billing" } }, [key])).not.toBeNull();
  });
  it("names a single agent", () => {
    expect(addLabel([{ name: "Planner" }])).toBe("Add Planner to AgentFox");
  });
});

describe("pendingPrompt counts each agent once", () => {
  it("an agent init found in two files is one agent to add", () => {
    const live = {
      connected: true,
      connectedAt: "2026-11-09T12:00:00Z",
      structure: { project: "lg" },
      pending: [
        { slug: "billing", name: "billing" },
        { slug: "billing", name: "billing" },
        { slug: "support-triage", name: "support-triage" },
        { slug: "support-triage", name: "support-triage" },
      ],
    };
    const p = pendingPrompt(live, [])!;
    expect(p.agents.map((a) => a.slug)).toEqual(["billing", "support-triage"]);
    expect(addLabel(p.agents)).toBe("Add 2 agents to AgentFox");
  });
});
