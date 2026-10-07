import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiBase, env, resetLegacyEnvWarnings } from "./env";

const NAMES = ["AGENTFOX_API_URL", "NOMETRIA_API_URL", "AGENTFOX_USER", "NOMETRIA_USER"];

describe("env", () => {
  const saved: Record<string, string | undefined> = {};

  beforeEach(() => {
    for (const name of NAMES) {
      saved[name] = process.env[name];
      delete process.env[name];
    }
    resetLegacyEnvWarnings();
  });

  afterEach(() => {
    for (const name of NAMES) {
      if (saved[name] === undefined) delete process.env[name];
      else process.env[name] = saved[name];
    }
    vi.restoreAllMocks();
  });

  it("reads AGENTFOX_ first", () => {
    process.env.AGENTFOX_API_URL = "https://new.example";
    process.env.NOMETRIA_API_URL = "https://old.example";
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(env("API_URL")).toBe("https://new.example");
    expect(warn).not.toHaveBeenCalled();
  });

  it("falls back to NOMETRIA_ and warns once per name", () => {
    process.env.NOMETRIA_USER = "old@example.com";
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(env("USER")).toBe("old@example.com");
    expect(env("USER")).toBe("old@example.com");
    expect(warn).toHaveBeenCalledTimes(1);
    expect(String(warn.mock.calls[0][0])).toContain("AGENTFOX_USER");
  });

  it("treats an empty value as unset", () => {
    process.env.AGENTFOX_API_URL = "";
    expect(apiBase()).toBe("http://127.0.0.1:8080");
  });
});
