import { describe, expect, it } from "vitest";
import { noticeText, withoutNoticeParams } from "./notice";

describe("noticeText", () => {
  it("says the agent controls in plain words", () => {
    expect(noticeText("agent quarantined")).toBe("Agent paused.");
    expect(noticeText("agent killed")).toBe("Agent stopped.");
    expect(noticeText("agent resumed")).toBe("Agent resumed.");
  });
  it("names the request an approval decided", () => {
    expect(noticeText("approved")).toBe("Request approved.");
    expect(noticeText("denied")).toBe("Request denied.");
  });
  it("drops the old page prefixes", () => {
    expect(noticeText("Done: agent quarantined.")).toBe("Agent paused.");
    expect(noticeText("Request approved.")).toBe("Request approved.");
  });
  it("capitalises anything else and ends it once", () => {
    expect(noticeText("breaker settings saved")).toBe("Breaker settings saved.");
    expect(noticeText("Retention updated.")).toBe("Retention updated.");
    expect(noticeText("")).toBe("");
    expect(noticeText(undefined)).toBe("");
  });
});

describe("withoutNoticeParams", () => {
  it("removes only the notice params", () => {
    expect(withoutNoticeParams("https://app.test/app/approvals?tab=history&review_notice=approved#x")).toBe("/app/approvals?tab=history#x");
    expect(withoutNoticeParams("/app/projects/a?review_error=nope")).toBe("/app/projects/a");
  });
  it("says when there was nothing to remove", () => {
    expect(withoutNoticeParams("/app/approvals?tab=history")).toBeNull();
  });
});
