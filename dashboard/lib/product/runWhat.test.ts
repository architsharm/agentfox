import { describe, expect, it } from "vitest";

import { handoffTarget, runSteps, runTitle, runWhat, slugOf } from "./runWhat";

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
  it("finds the agent by its slug however the code wrote the name, and never shows a code name", () => {
    // `agentfox init` keeps the name as the code wrote it: restaurant_scout, slug restaurant-scout.
    const names = new Map([
      ["restaurant-scout", "restaurant_scout"],
      ["currency-agent", "CurrencyAgent"],
    ]);
    expect(handoffTarget("transfer_to_restaurant_scout", names)).toBe("Restaurant Scout");
    expect(handoffTarget("transfer_to_CurrencyAgent", names)).toBe("CurrencyAgent");
    expect(handoffTarget("transfer_to_restaurant_scout")).toBe("Restaurant Scout");
    expect(slugOf("FinancialPlannerAgent")).toBe("financial-planner-agent");
    expect(slugOf("restaurant_scout")).toBe("restaurant-scout");
  });
});

describe("runTitle", () => {
  it("is what the person asked in the turn, when recorded", () => {
    expect(runTitle({ asked: "plan a weekend in Lisbon" }, [{ tool: "transfer_to_restaurant_scout" }])).toBe("plan a weekend in Lisbon");
    expect(runTitle({ asked: "x".repeat(200) }).length).toBe(120);
  });
  it("otherwise says what the run did, in words", () => {
    expect(runTitle({}, [{ tool: "transfer_to_restaurant_scout", surface: "tool_args" }])).toBe("Handed off to Restaurant Scout");
    expect(runTitle({}, [{ tool: "file_read" }])).toBe("Called file_read");
    expect(runTitle({}, [{ surface: "input" }], { input: "User message" })).toBe("User message");
    expect(runTitle({}, [])).toBe("Run");
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
