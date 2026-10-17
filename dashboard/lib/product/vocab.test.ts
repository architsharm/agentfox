import { describe, expect, it } from "vitest";
import { sentence } from "./vocab";

describe("sentence", () => {
  it("capitalises a title that opens with a plain word", () => {
    expect(sentence("the answer reaches a legal conclusion")).toBe("The answer reaches a legal conclusion");
  });
  it("never changes an identifier at the start", () => {
    expect(sentence("support-triage tried to email.send")).toBe("support-triage tried to email.send");
    expect(sentence("email.send was held")).toBe("email.send was held");
    expect(sentence("11/11 red-team probes")).toBe("11/11 red-team probes");
  });
});
