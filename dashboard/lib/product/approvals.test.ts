import { describe, expect, it } from "vitest";
import { actionArguments, actionLabel, actionSummary, decidedBy, firstSentence, readableReason } from "./approvals";

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
});
