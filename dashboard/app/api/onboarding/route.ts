import { proxyJson } from "@/lib/product/proxy";

/**
 * Setup progress for the browser: Get started polls this while it waits for an
 * agent's first request, so the page can say "received" without a reload.
 */
export async function GET() {
  return proxyJson("/api/onboarding", "GET", undefined, { cache: "no-store" });
}
