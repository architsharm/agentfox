import { describe, expect, it } from "vitest";
import { ruleTitle, sentence } from "./vocab";

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

describe("ruleTitle for init's first guardrails", () => {
  it("uses the description written for people, not the id", () => {
    expect(ruleTitle("watch.llm_out.secrets", "Secrets in what the LLM answers")).toBe("Secrets in what the LLM answers");
  });
});
