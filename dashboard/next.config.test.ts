import { describe, expect, it } from "vitest";
import nextConfig from "./next.config.mjs";

/** The security headers every response carries (see next.config.mjs). */
describe("next.config security headers", () => {
  it("refuses framing and sends the baseline headers on every path", async () => {
    const rules = await nextConfig.headers!();
    const all = rules.find((r: { source: string }) => r.source === "/:path*");
    expect(all, "a rule covering every path").toBeDefined();
    const byKey = Object.fromEntries(
      all!.headers.map((h: { key: string; value: string }) => [h.key.toLowerCase(), h.value]),
    );
    expect(byKey["x-frame-options"]).toBe("DENY");
    expect(byKey["content-security-policy"]).toContain("frame-ancestors 'none'");
    expect(byKey["x-content-type-options"]).toBe("nosniff");
    expect(byKey["referrer-policy"]).toBe("strict-origin-when-cross-origin");
    expect(byKey["strict-transport-security"]).toMatch(/max-age=\d+/);
    expect(byKey["permissions-policy"]).toContain("camera=()");
  });

  it("does not advertise the framework or ship browser source maps", () => {
    expect(nextConfig.poweredByHeader).toBe(false);
    expect(nextConfig.productionBrowserSourceMaps).not.toBe(true);
  });
});
