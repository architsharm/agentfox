import { describe, expect, it } from "vitest";

import { handoffTarget, runSteps, runWhat } from "./runWhat";

describe("runWhat", () => {
  it("keeps what the person asked", () => {
    expect(runWhat({ summary: "Is Globex cheaper than you?" })).toBe("Is Globex cheaper than you?");
  });
  it("renders an Agents SDK hand-off in words, not JSON", () => {
    expect(runWhat({ summary: '{"assistant": "FAQ Agent"}' })).toBe("Handed off to FAQ Agent");
    expect(runWhat({ tools: ["transfer_to_faq_agent"] })).toBe("Handed off to FAQ Agent");
    expect(handoffTarget("transfer_to_seat_booking_agent")).toBe("Seat Booking Agent");
  });
  it("never headlines a tool's JSON output", () => {
    expect(runWhat({ summary: '{"balance": 120, "currency": "USD"}', tools: ["accounts.lookup"] })).toBe("accounts.lookup");
    expect(runWhat({ summary: "[1, 2]" })).toBe("Model call");
  });
  it("names a hand-off's agent by its display name when it is one of yours", () => {
    const names = new Map([["faq-agent", "Help Desk"]]);
    expect(runWhat({ tools: ["transfer_to_faq_agent"] }, {}, names)).toBe("Handed off to Help Desk");
    expect(handoffTarget("transfer_to_seat_booking_agent", names)).toBe("Seat Booking Agent");
  });
});

describe("runSteps", () => {
  it("says what a turn folded: its steps, its tools, its hand-offs in words", () => {
    expect(runSteps({ summary: "please list the files here", runs: 3, tools: ["file_read"] })).toBe("3 steps · file_read");
    expect(runSteps({ summary: "book me a seat", runs: 2, tools: ["transfer_to_seat_booking_agent"] })).toBe(
      "2 steps · handed off to Seat Booking Agent",
    );
  });
  it("does not repeat tools that already head the row, and is empty for a single step", () => {
    expect(runSteps({ runs: 2, tools: ["file_read"] })).toBe("2 steps");
    expect(runSteps({ summary: "hi there", runs: 1, tools: [] })).toBe("");
  });
});
