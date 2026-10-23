import { describe, expect, it } from "vitest";
import { ruleTitle, sentence, wouldDo } from "./vocab";

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

describe("ruleTitle from a rule id", () => {
  it("keeps acronyms upper case", () => {
    expect(ruleTitle("code.pii_out_of_a_developer_machine")).toBe("PII out of a developer machine");
    expect(ruleTitle("tool.api_key_in_url")).toBe("API key in URL");
    expect(ruleTitle("compliance.eu_ai_act_disclosure")).toBe("EU AI act disclosure");
    expect(ruleTitle("tool.mcp_server_llm_call")).toBe("MCP server LLM call");
    expect(ruleTitle("code.sql_by_id")).toBe("SQL by ID");
  });
  it("leaves words that merely contain one alone", () => {
    expect(ruleTitle("actions.email_identity_check")).toBe("Email identity check");
  });
});

describe("wouldDo", () => {
  it("says what a watching rule would do", () => {
    expect(wouldDo("Blocks")).toBe("Would block");
    expect(wouldDo("Asks a person")).toBe("Would ask a person");
    expect(wouldDo("Hides")).toBe("Would hide");
    expect(wouldDo("Asks")).toBe("Would ask");
  });
});
