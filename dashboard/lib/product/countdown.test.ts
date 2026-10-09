import { describe, expect, it } from "vitest";
import { formatCountdown } from "./countdown";

describe("formatCountdown", () => {
  const now = new Date("2026-10-09T12:00:00Z");
  const at = (ms: number) => formatCountdown(new Date(now.getTime() + ms), now);

  it("does not read as over while under a minute is left", () => {
    expect(at(30_000)).toEqual({ label: "<1m", tone: "warn" });
    expect(at(-1)).toEqual({ label: "expired", tone: "bad" });
  });

  it("counts minutes, hours and days", () => {
    expect(at(5 * 60_000).label).toBe("5m");
    expect(at(90 * 60_000).label).toBe("1h 30m");
    expect(at(26 * 3600_000).label).toBe("1d 2h");
  });
});
