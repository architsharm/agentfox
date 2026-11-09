import { describe, expect, it } from "vitest";

import { controlShare } from "./posture";

describe("controlShare", () => {
  it("counts working controls out of every control that applies", () => {
    // The audit's workspace: Compliance said 88% of 40 measured, Summary 35 of 43.
    const p = {
      controls: 44,
      counts: { effective: 35, degraded: 3, failing: 2, not_implemented: 3, not_applicable: 1, not_computed: 0 },
    };
    const s = controlShare(p);
    expect(s).toMatchObject({ working: 35, applies: 43, measured: 40, notSetUp: 3 });
    expect(Math.round((s.share ?? 0) * 100)).toBe(81);
  });

  it("takes the gateway's own figure, the one `agentfox report status` prints", () => {
    const p = {
      controls: 44,
      counts: { effective: 20, degraded: 5, failing: 2, not_implemented: 16, not_applicable: 1 },
      applies: 43,
      working: 20,
      measured: 27,
      share: 0.4651,
    };
    const s = controlShare(p);
    expect(s).toMatchObject({ working: 20, applies: 43, measured: 27, notSetUp: 16, share: 0.4651 });
  });

  it("is null, not 0%, with nothing that applies", () => {
    expect(controlShare({ controls: 0, counts: {} }).share).toBeNull();
    expect(controlShare(null).share).toBeNull();
  });
});
