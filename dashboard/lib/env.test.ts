import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { apiBase, env } from "./env";

const NAMES = ["AGENTFOX_API_URL", "AGENTFOX_USER"];

describe("env", () => {
  const saved: Record<string, string | undefined> = {};

  beforeEach(() => {
    for (const name of NAMES) {
      saved[name] = process.env[name];
      delete process.env[name];
    }
  });

  afterEach(() => {
    for (const name of NAMES) {
      if (saved[name] === undefined) delete process.env[name];
      else process.env[name] = saved[name];
    }
  });

  it("reads AGENTFOX_<name>", () => {
    process.env.AGENTFOX_API_URL = "https://new.example";
    expect(env("API_URL")).toBe("https://new.example");
    expect(apiBase()).toBe("https://new.example");
  });

  it("is undefined when unset", () => {
    expect(env("USER")).toBeUndefined();
  });

  it("treats an empty value as unset", () => {
    process.env.AGENTFOX_API_URL = "";
    expect(apiBase()).toBe("http://127.0.0.1:8080");
  });
});
