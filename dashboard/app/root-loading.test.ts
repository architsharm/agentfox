import { existsSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * A loading.tsx at the root of app/ wraps every public page in a Suspense
 * boundary. The public pages are dynamic (the header reads the session cookie),
 * so each one was streamed as that boundary's fallback with the real page in a
 * `<div hidden>` that only JavaScript swaps in. Production served the dashboard
 * skeleton, or a blank page on /benchmark, to every visitor and crawler without
 * JavaScript, and flashed it at everyone else. The app's own boundary lives at
 * app/(product)/app/loading.tsx, inside the app shell, where it belongs.
 */
describe("loading boundaries", () => {
  it("has none at the root, so public pages render without JavaScript", () => {
    expect(existsSync(path.join(__dirname, "loading.tsx"))).toBe(false);
  });

  it("keeps the app's own, inside the app shell", () => {
    expect(existsSync(path.join(__dirname, "(product)", "app", "loading.tsx"))).toBe(true);
  });
});
