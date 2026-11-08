import { describe, expect, it } from "vitest";
import { actionArguments, actionLabel, actionSummary, approvalOutcome, decidedBy, firstSentence, minutesLabel, onExpiry, readableReason, waitMinutes } from "./approvals";

const message = {
  tool: "message:input",
  arguments: { surface: "input", content: "Is Delta cheaper?", content_sha256: "1db3" },
};
const call = { tool: "airline.cancel_flight", arguments: { confirmation_number: "LL0EZ6", amount: 900 } };

describe("approvals display", () => {
  it("shows a held message as its content, not its digest", () => {
    expect(actionLabel(message)).toBe("Message in");
    expect(actionLabel({ tool: "message:output" })).toBe("Reply");
    expect(actionArguments(message)).toEqual([["content", "Is Delta cheaper?"]]);
    expect(actionSummary(message)).toBe("Is Delta cheaper?");
    expect(actionSummary(message)).not.toContain("1db3");
  });

  it("shows a tool call as the tool and its arguments", () => {
    expect(actionLabel(call)).toBe("airline.cancel_flight");
    expect(actionSummary(call)).toBe("confirmation_number: LL0EZ6 · amount: 900");
  });

  it("does not cut a reason at an abbreviation", () => {
    expect(firstSentence("EU AI Act Art. 14 needs human oversight here. Second one.")).toBe(
      "EU AI Act Art. 14 needs human oversight here.",
    );
  });

  it("reads several joined reasons as prose", () => {
    expect(readableReason("Needs approval.; Irreversible action.")).toBe("Needs approval. Irreversible action.");
    expect(readableReason("Off task.; Needs approval.; Off task.")).toBe("Off task. Needs approval.");
    expect(readableReason("rule a; rule b")).toBe("rule a; rule b");
    expect(firstSentence("The granting capability requires approval.; Irreversible action attempted.")).toBe(
      "The granting capability requires approval.",
    );
  });

  it("names who decided, or that nobody did", () => {
    expect(decidedBy({ status: "pending" })).toBeNull();
    expect(decidedBy({ status: "denied", resolver: "you@example.com" })).toBe("you@example.com");
    expect(decidedBy({ status: "expired" })).toBe("Nobody answered");
  });

  it("says how long an unanswered request waited", () => {
    const a = { status: "expired", requested_at: "2026-11-01T10:00:00+00:00", expires_at: "2026-11-01T10:20:00+00:00" };
    expect(waitMinutes(a)).toBe(20);
    expect(decidedBy(a)).toBe("Nobody answered in 20 min");
    expect(waitMinutes({ requested_at: "2026-11-01T10:00:00Z", expires_at: null })).toBeNull();
    expect(waitMinutes({ requested_at: "2026-11-01T10:20:00Z", expires_at: "2026-11-01T10:00:00Z" })).toBeNull();
  });

  it("puts a span of minutes in words", () => {
    expect(minutesLabel(30)).toBe("30 min");
    expect(minutesLabel(60)).toBe("1 h");
    expect(minutesLabel(65)).toBe("1 h 5 min");
    expect(minutesLabel(3 * 24 * 60)).toBe("3 days");
  });

  it("says what happens on expiry, failing closed by default", () => {
    expect(onExpiry("deny")).toMatch(/denied/);
    expect(onExpiry(undefined)).toMatch(/denied/);
    expect(onExpiry("allow")).toMatch(/approved/);
  });
});

describe("a held call's outcome on its run", () => {
  it("says who approved or denied it, and nothing while it waits", () => {
    expect(approvalOutcome({ status: "pending" })).toBeNull();
    expect(approvalOutcome(null)).toBeNull();
    expect(approvalOutcome({ status: "approved", resolver: "ana@x.test" })).toEqual({ label: "Approved by ana@x.test", tone: "ok" });
    expect(approvalOutcome({ status: "used", resolver: "ana@x.test" })?.label).toBe("Approved by ana@x.test · ran");
    expect(approvalOutcome({ status: "denied", resolver: "bo@x.test" })).toEqual({ label: "Denied by bo@x.test", tone: "bad" });
    expect(approvalOutcome({ status: "expired" })?.label).toBe("Nobody answered · denied");
  });
});
