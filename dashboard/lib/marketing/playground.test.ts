import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, explainVerdict, failureMessage, playgroundCall, retryPhrase } from "@/lib/marketing/playground";

afterEach(() => {
  vi.unstubAllGlobals();
});

/** A gateway that accepts the connection and never answers. */
function hangingFetch() {
  return vi.fn(
    (_url: string, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(init.signal!.reason));
      }),
  );
}

describe("playgroundCall", () => {
  it("gives up on a gateway that never answers instead of waiting forever", async () => {
    vi.stubGlobal("fetch", hangingFetch());
    const call = playgroundCall("http://gw", "/api/playground/sessions", { method: "POST" }, 50);
    // Not an ApiError, so the page shows its "could not be reached" message
    // and the button to start a new sandbox.
    await expect(call).rejects.not.toBeInstanceOf(ApiError);
    await expect(call).rejects.toThrow();
  });

  it("carries the gateway's own sentence on an error response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "Too many sandboxes." }), { status: 429 })),
    );
    const err = await playgroundCall("http://gw", "/api/playground/sessions").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(429);
    expect(err.message).toBe("Too many sandboxes.");
  });

  it("returns the body of a successful response", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ session_id: "pg_1" }), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(playgroundCall("http://gw", "/api/playground/sessions")).resolves.toEqual({
      session_id: "pg_1",
    });
    expect(fetchMock).toHaveBeenCalledWith("http://gw/api/playground/sessions", expect.anything());
  });
});

describe("failureMessage", () => {
  it("passes the gateway's own sentence through", () => {
    expect(failureMessage(new ApiError(400, "Message is too long."))).toBe("Message is too long.");
  });

  it("never shows the browser's raw network error", () => {
    const msg = failureMessage(new TypeError("Failed to fetch"));
    expect(msg).not.toMatch(/fetch/i);
    expect(msg).toMatch(/could not be reached/);
  });

  it("says a timeout is a timeout", () => {
    expect(failureMessage(new DOMException("signal timed out", "TimeoutError"))).toMatch(/too long/);
  });
});

describe("rate limit", () => {
  it("carries when to retry from a 429", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ detail: "Later.", retry_after_seconds: 1500 }), { status: 429 }),
      ),
    );
    const err = await playgroundCall("http://gw", "/api/playground/sessions").catch((e) => e);
    expect(err.retryAfterSeconds).toBe(1500);
    expect(retryPhrase(err.retryAfterSeconds)).toBe("in about 25 minutes");
    expect(retryPhrase(undefined)).toBe("in a minute");
  });
});

describe("explainVerdict", () => {
  it("turns the joined reasons into one sentence and moves citations aside", () => {
    const v = {
      reason:
        "Prompt-injection or jailbreak attempt detected in user input.; System-prompt extraction attempt.; EU AI Act Art. 15 - resilience against attempts to alter system behaviour.; Prompt-injection or jailbreak attempt detected in user input.",
      rules_fired: [
        { rule_id: "injection.direct", reason: "Prompt-injection or jailbreak attempt detected in user input." },
        { rule_id: "injection.system_prompt_leak", reason: "System-prompt extraction attempt." },
        { rule_id: "eu.art15.injection_resistance", reason: "EU AI Act Art. 15 - resilience against attempts to alter system behaviour." },
        { rule_id: "injection.direct", reason: "Prompt-injection or jailbreak attempt detected in user input." },
      ],
    };
    const out = explainVerdict(v);
    expect(out.sentence).toBe("Prompt-injection or jailbreak attempt detected in user input (and 1 more check).");
    expect(out.sentence).not.toContain(".;");
    expect(out.citations).toEqual(["EU AI Act Art. 15 - resilience against attempts to alter system behaviour."]);
  });

  it("names a custom rule in words", () => {
    const out = explainVerdict({
      rules_fired: [{ rule_id: "custom.airline-cs-words", reason: "airline-cs: blocked words: your rule" }],
    });
    expect(out.sentence).toBe("It matched this agent's blocked words.");
  });

  it("falls back to the first reason when no rule is listed", () => {
    expect(explainVerdict({ reason: "Over the limit.; Something else." }).sentence).toBe("Over the limit.");
  });
});
