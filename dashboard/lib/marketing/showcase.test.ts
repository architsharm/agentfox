import { describe, expect, it } from "vitest";

import { ofTotal, toFeed } from "@/lib/marketing/showcase";

const LIVE = {
  enabled: true,
  last_updated: "2026-10-06T01:00:00+00:00",
  totals: { runs: 1, attacks_attempted: 9, contained: 6, escaped: 3, errors: 0, over_blocked: 0 },
  latest: { run: null, headline: null, results: [] },
  runs: [],
  findings: { open: 3, opened_in_window: 3, closed_in_window: 0, recent: [] },
};

describe("the /live feed", () => {
  it("shows data only when the gateway says the showcase is running", () => {
    expect(toFeed(200, LIVE).state).toBe("live");
    expect(toFeed(200, { enabled: false, last_updated: null })).toEqual({ state: "off" });
  });

  it("never turns a failure into numbers", () => {
    expect(toFeed(503, null).state).toBe("unavailable");
    expect(toFeed(200, "nope").state).toBe("unavailable");
    expect(toFeed(200, { enabled: true }).state).toBe("unavailable");
  });

  it("says counts, not percentages of tiny numbers", () => {
    expect(ofTotal(3, 9)).toBe("3 of 9");
    expect(ofTotal(0, 9)).toBe("none of 9");
    expect(ofTotal(0, 0)).toBe("0");
  });
});
