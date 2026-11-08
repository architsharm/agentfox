import { describe, expect, it } from "vitest";
import { businessRuleName, defaultRuleScope, inlineMarkdown, parsePyDict, splitControls, suggestedLadderName, unusedSentences, versionNote } from "./policyWords";

describe("a rule's description", () => {
  it("renders the inline marks rule docstrings use", () => {
    expect(inlineMarkdown("it is the *higher* severity, **always**, see `tool_result`.")).toEqual([
      { kind: "text", text: "it is the " },
      { kind: "em", text: "higher" },
      { kind: "text", text: " severity, " },
      { kind: "strong", text: "always" },
      { kind: "text", text: ", see " },
      { kind: "code", text: "tool_result" },
      { kind: "text", text: "." },
    ]);
    expect(inlineMarkdown("2 * 3 is six")).toEqual([{ kind: "text", text: "2 * 3 is six" }]);
  });

  it("moves control IDs out of the sentence", () => {
    const out = splitControls("on the two surfaces that predate this policy (NOM-RTG-13, NOM-IAM-08).\n");
    expect(out.controls).toEqual(["NOM-RTG-13", "NOM-IAM-08"]);
    expect(out.text).toBe("on the two surfaces that predate this policy.");
    expect(splitControls("Block high-confidence injection.")).toEqual({ text: "Block high-confidence injection.", controls: [] });
  });
});

describe("a version's notes", () => {
  const title = (id: string) => (id === "injection.direct" ? "Jailbreaks & prompt injection" : id);

  it("reads the Python dict the gateway writes", () => {
    expect(parsePyDict("{'min_score': 0.5}")).toEqual({ min_score: 0.5 });
    expect(parsePyDict(`{'enabled': False, 'message': "Can't do that", 'x': None}`)).toEqual({ enabled: false, message: "Can't do that", x: null });
    expect(parsePyDict("not a dict")).toBeNull();
    expect(parsePyDict("{'a': [1, 2]}")).toBeNull();
  });

  it("turns a one-rule change into words", () => {
    expect(versionNote("injection.direct: {'min_score': 0.5}", title)).toEqual({ text: "Sensitivity set to High", rule: "Jailbreaks & prompt injection" });
    expect(versionNote("injection.direct: {'min_score': 0.5} (was {'min_score': 0.7})").text).toBe("Sensitivity changed from Medium to High");
    expect(versionNote("x.y: {'effect': 'escalate'} (was {'effect': 'block'})").text).toBe("Action changed from Block to Ask a human");
    expect(versionNote("x.y: {'enabled': False, 'overridable': True}").text).toBe("Turned off · Agents may now loosen this rule");
  });

  it("leaves notes a person wrote as they are", () => {
    expect(versionNote("loaded by agentfox init")).toEqual({ text: "Loaded by agentfox init" });
    expect(versionNote(null)).toEqual({ text: "" });
  });
});

describe("business rule names", () => {
  it("keeps a name a person typed", () => {
    expect(businessRuleName({ key: "custom-x", name: "Big transfers need finance", tool: "payments.transfer" })).toBe("Big transfers need finance");
  });

  it("says what a rule named only by its key does", () => {
    expect(businessRuleName({ key: "custom-payments-transfer", name: "custom-payments-transfer", tool: "payments.transfer", kind: "threshold_ladder" })).toBe(
      "Approval limit on payments.transfer",
    );
    expect(businessRuleName({ key: "k", name: "", tool: null })).toBe("Approval limit");
  });

  it("suggests a name from the bands", () => {
    const def = { tool: "payments.transfer", unit: "USD", bands: [{ upto: 100, outcome: "allow" }, { upto: null, outcome: "escalate" }] };
    expect(suggestedLadderName(def)).toBe("Approval above $100 on payments.transfer");
    expect(suggestedLadderName({ tool: "*", bands: [{ upto: null, outcome: "escalate" }] })).toBe("Approval limit");
  });
});

describe("who a new rule applies to", () => {
  it("starts on the agent it was opened for, else the project's only agent, else every agent", () => {
    expect(defaultRuleScope("pay", [{ slug: "a" }, { slug: "b" }])).toBe("pay");
    expect(defaultRuleScope(undefined, [{ slug: "a" }])).toBe("a");
    expect(defaultRuleScope(undefined, [{ slug: "a" }, { slug: "b" }])).toBe("");
    expect(defaultRuleScope(undefined, [])).toBe("");
  });
});

describe("sentences that compiled to nothing", () => {
  const rules = [{ definition: { bands: [{ upto: 100, outcome: "allow" }, { upto: null, outcome: "escalate" }] } }];

  it("does not list the sentence that became the allow band", () => {
    expect(unusedSentences(["Payments transfers up to $100 can run automatically."], rules)).toEqual([]);
  });

  it("still lists a sentence that really went unused", () => {
    expect(unusedSentences(["Be nice to customers.", "Transfers up to $250 run automatically."], rules)).toEqual([
      "Be nice to customers.",
      "Transfers up to $250 run automatically.",
    ]);
    expect(unusedSentences(["Anything."], [])).toEqual(["Anything."]);
  });
});
