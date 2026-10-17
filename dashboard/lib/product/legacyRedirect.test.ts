import { describe, expect, it, vi } from "vitest";

const redirectMock = vi.fn((url: string) => {
  // Next's real redirect() throws internally (NEXT_REDIRECT) so nothing after
  // the call in the caller ever runs — mirror that so a bug that reads code
  // after redirect() as reachable would show up as a real test failure.
  throw new Error(`NEXT_REDIRECT:${url}`);
});
vi.mock("next/navigation", () => ({ redirect: redirectMock }));

const { legacyTabRedirect } = await import("./legacyRedirect");

describe("legacyTabRedirect", () => {
  it("sets tab and forwards no other params when there are none", async () => {
    await expect(
      legacyTabRedirect(Promise.resolve({}), "/app/compliance", "board"),
    ).rejects.toThrow("NEXT_REDIRECT:/app/compliance?tab=board");
  });

  it("forwards existing query params from the old URL alongside tab", async () => {
    await expect(
      legacyTabRedirect(
        Promise.resolve({ agent: "support-triage", severity: "high" }),
        "/app/compliance",
        "board",
      ),
    ).rejects.toThrow(
      "NEXT_REDIRECT:/app/compliance?agent=support-triage&severity=high&tab=board",
    );
  });

  it("a tab param on the old URL is overwritten by the new destination tab, not duplicated", async () => {
    // The bookmarked URL shouldn't be able to send the redirect somewhere
    // other than the tab this route exists to forward to.
    await expect(
      legacyTabRedirect(Promise.resolve({ tab: "old-tab" }), "/app/compliance", "board"),
    ).rejects.toThrow("NEXT_REDIRECT:/app/compliance?tab=board");
  });

  it("drops non-string param values rather than passing through [object Object] or similar", async () => {
    await expect(
      legacyTabRedirect(
        // Next's searchParams type allows string | string[] | undefined for a
        // repeated query key — this proves an array value is silently dropped
        // rather than corrupting the redirect URL.
        Promise.resolve({ agent: undefined, ok: "yes" } as Record<string, string | undefined>),
        "/app/compliance",
        "board",
      ),
    ).rejects.toThrow("NEXT_REDIRECT:/app/compliance?ok=yes&tab=board");
  });
});
