import { describe, expect, it } from "vitest";
import { detailText } from "./errors";

describe("detailText", () => {
  it("reads a refusal as a sentence, keeping its next step", () => {
    expect(detailText("simulate first: Basic guardrails has not been simulated. Click Simulate, then start blocking.")).toBe(
      "Simulate first: Basic guardrails has not been simulated. Click Simulate, then start blocking.",
    );
    expect(detailText("'x' is unknown")).toBe("'x' is unknown");
  });
  it("joins validation errors", () => {
    expect(detailText([{ loc: ["body", "name"], msg: "required" }])).toBe("name: required");
  });
});
