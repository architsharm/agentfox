import { describe, expect, it } from "vitest";
import { coverageNumbers } from "@/lib/product/coverage";

describe("coverageNumbers", () => {
  it("counts enforcing rules by policy mode, not by policy count", () => {
    // Three policies, 34 rules, but only the two enforcing ones contribute —
    // a 15-rule policy left in observe must not read as 15 rules enforcing.
    const c = coverageNumbers({
      policies: [
        { mode: "enforce", rules: 12 },
        { mode: "observe", rules: 7 },
        { mode: "enforce", rules: 15 },
      ],
      detectors: [],
      probes: [],
      controls: {},
    });
    expect(c.rulesTotal).toBe(34);
    expect(c.rulesEnforcing).toBe(27);
    expect(c.rulesObserving).toBe(7);
  });

  it("uses available, not installed, as the detector denominator", () => {
    // A check the build knows about but that isn't installed here is not a gap
    // the reader can close, so it belongs in the hint and not in the ratio.
    const c = coverageNumbers({
      policies: [],
      detectors: [
        { enabled: true, available: true },
        { enabled: false, available: true },
        { enabled: false, available: false },
      ],
      probes: [],
      controls: {},
    });
    expect(c.detectorsOn).toBe(1);
    expect(c.detectorsAvailable).toBe(2);
    expect(c.detectorsInstalled).toBe(3);
  });

  it("excludes unassessed controls from the effectiveness denominator", () => {
    // not_implemented / not_applicable / not_computed are not passes and not
    // failures — counting them either way misstates the posture.
    const c = coverageNumbers({
      policies: [],
      detectors: [],
      probes: [],
      controls: {
        counts: {
          effective: 35,
          degraded: 3,
          failing: 2,
          not_implemented: 0,
          not_applicable: 1,
          not_computed: 4,
        },
      },
    });
    expect(c.controlsEffective).toBe(35);
    expect(c.controlsAssessed).toBe(40);
  });

  it("does not divide by zero on an empty deployment", () => {
    const c = coverageNumbers({ policies: [], detectors: [], probes: [], controls: {} });
    expect(c).toMatchObject({
      rulesTotal: 0,
      rulesEnforcing: 0,
      rulesObserving: 0,
      detectorsOn: 0,
      detectorsAvailable: 0,
      probes: 0,
      controlsEffective: 0,
      controlsAssessed: 0,
    });
  });
});
