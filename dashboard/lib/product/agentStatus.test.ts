import { describe, expect, it } from "vitest";
import { appReturnPath, breakerLabel, breakerRule, controlNotice, noticeSentence, refusalText, stateLabel } from "./agentStatus";

const O = "https://app.example.com";
const F = "/app/projects/support";

describe("appReturnPath", () => {
  it("keeps an in-app path with its query", () => {
    expect(appReturnPath("/app/projects/support?view=access", O, F)).toBe("/app/projects/support?view=access");
    expect(appReturnPath("/app", O, F)).toBe("/app");
  });
  it("accepts a same-origin absolute URL (a Referer)", () => {
    expect(appReturnPath("https://app.example.com/app/findings?agent=x#top", O, F)).toBe("/app/findings?agent=x#top");
  });
  it("drops the last action's notice and error", () => {
    expect(appReturnPath("/app/projects/support?view=controls&review_notice=x&review_error=y", O, F)).toBe("/app/projects/support?view=controls");
  });
  it("refuses other hosts, protocol-relative and odd paths", () => {
    expect(appReturnPath("https://evil.example/app/x", O, F)).toBe(F);
    expect(appReturnPath("//evil.example/app/x", O, F)).toBe(F);
    expect(appReturnPath("/\\evil.example", O, F)).toBe(F);
    expect(appReturnPath("javascript:alert(1)", O, F)).toBe(F);
    expect(appReturnPath("/docs/x", O, F)).toBe(F);
    expect(appReturnPath("/application", O, F)).toBe(F);
    expect(appReturnPath("/app/../api/x", O, F)).toBe(F);
    expect(appReturnPath("", O, F)).toBe(F);
    expect(appReturnPath(null, O, F)).toBe(F);
  });
});

describe("words", () => {
  it("never shows the API's state names", () => {
    expect(stateLabel("quarantined")).toBe("Paused");
    expect(stateLabel("killed")).toBe("Stopped");
    expect(stateLabel("active")).toBe("Active");
    expect(stateLabel(undefined)).toBe("Active");
  });
  it("words the notice plainly", () => {
    expect(noticeSentence(controlNotice("quarantine", "Support agent"))).toBe("Support agent paused.");
    expect(noticeSentence(controlNotice("resume", ""))).toBe("Agent resumed.");
    expect(noticeSentence("breaker closed")).toBe("Breaker closed.");
  });
  it("quotes the refusal exactly as the gateway builds it", () => {
    expect(refusalText("quarantined", "ticket 42", "a@b.co")).toBe("Agent is paused: ticket 42 (by a@b.co)");
    expect(refusalText("killed")).toBe("Agent is stopped");
  });
});

describe("breaker", () => {
  const b = { block_ratio: 0.5, min_calls: 20, window_seconds: 300, cooldown_seconds: 60, probe_calls: 3 };
  it("states the trip rule in one sentence", () => {
    expect(breakerRule({ ...b, mode: "pause" })).toBe(
      "Trips when 50% of at least 20 calls in 5 min are blocked; then refuses this agent's calls for 1 min and lets them through again after 3 clean calls.",
    );
    expect(breakerRule({ ...b, mode: "alert" })).toBe("Trips when 50% of at least 20 calls in 5 min are blocked; then raises an issue. Calls are not refused.");
    expect(breakerRule({ ...b, mode: "off" })).toMatch(/off/);
  });
  it("does not call an alert-only trip refusing", () => {
    expect(breakerLabel({ mode: "alert", state: "open" })[0]).toBe("Tripped: issue raised");
    expect(breakerLabel({ mode: "pause", state: "open" })[0]).toBe("Open: calls refused");
    expect(breakerLabel({ mode: "pause", state: "closed" })[0]).toBe("Closed");
  });
});
