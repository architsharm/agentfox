import { describe, expect, it } from "vitest";
import { bannerFor, firstRequestSnippet, type Onboarding, type ProjectSetup } from "./setupBanner";

const ws = (extra: Partial<Onboarding> = {}): Onboarding => ({
  completed: 2,
  total: 6,
  connected: true,
  next: { id: "enforce", title: "Turn enforcement on" },
  counts: { agents: 2, traces: 5 },
  ...extra,
});

const proj = (next: ProjectSetup["next"], extra: Partial<ProjectSetup> = {}): ProjectSetup => ({
  agent: "billing",
  name: "Billing",
  id: "agt_1",
  status: "active",
  traces: 1,
  tools: 3,
  granted: 0,
  watching: [],
  next,
  ...extra,
});

describe("setup banner", () => {
  it("starts an empty workspace at connecting an agent", () => {
    expect(bannerFor(null, ws({ counts: { agents: 0, traces: 0 }, connected: false }))?.kind).toBe("connect");
  });

  it("waits for the first request before anything else", () => {
    expect(bannerFor(null, ws({ connected: false }))?.kind).toBe("first-request");
  });

  it("names the next step, and says nothing once setup is done", () => {
    expect(bannerFor(null, ws())?.body).toBe("Next: Turn enforcement on");
    expect(bannerFor(null, ws({ next: null }))).toBeNull();
  });

  it("is about the project when one is open", () => {
    expect(bannerFor(proj("traffic"), ws())?.snippet).toBe(firstRequestSnippet("billing"));
    expect(bannerFor(proj("tools"), ws())?.title).toBe("Billing may not use any of its 3 tools yet");
    expect(bannerFor(proj("enforce"), null)?.kind).toBe("enforce");
    expect(bannerFor(proj(null), ws())).toBeNull();
  });

  it("puts the project's slug in the test request", () => {
    expect(firstRequestSnippet("billing")).toContain('"agent": "billing"');
  });
});
