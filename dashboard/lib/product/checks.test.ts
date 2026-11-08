import { describe, expect, it } from "vitest";
import { checkIdle, checkName } from "./checks";

describe("check names", () => {
  it("never shows a raw key, and never two checks under one name", () => {
    expect(checkName({ key: "custom.validators", label: null })).toBe("Your validator rules");
    expect(checkName({ key: "injection.judgment", label: null })).toBe("Prompt injection (judge)");
    // Labelled "Prompt injection (judge)" upstream too: named by where it comes from.
    expect(checkName({ key: "validator.prompt_injection_llm", label: "Prompt injection (judge)" })).toBe("Prompt injection (Guardrails AI judge)");
    expect(checkName({ key: "validator.detect_jailbreak", label: "Jailbreak (classifier)" })).toBe("Jailbreak (classifier)");
    expect(checkName({ key: "pii.native", label: null })).toBe("Personal data");
    expect(checkName({ key: "validator.some_new_thing", label: null })).toBe("Some new thing");
  });
});

describe("a check that isn't running says why", () => {
  it("names what is missing", () => {
    expect(checkIdle({ available: true, enabled: true, source: "builtin" })).toBeNull();
    expect(checkIdle({ available: true, enabled: false, source: "builtin" })).toBe("off");
    expect(checkIdle({ available: false, enabled: true, source: "open_source", unavailable: "model not downloaded: run …" })).toBe("model not downloaded");
    expect(checkIdle({ available: false, source: "llm_judge" })).toBe("no judge on");
    expect(checkIdle({ available: false, source: "builtin", unavailable: "pip install x" })).toBe("not installed");
  });
});
