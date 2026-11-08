import { describe, expect, it } from "vitest";

import { handoffTarget, runWhat } from "./runWhat";

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
});
