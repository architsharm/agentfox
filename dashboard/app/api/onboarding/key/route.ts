import { proxyJson } from "@/lib/product/proxy";

/** The key for `agentfox init --key`. Always retrievable. */
export async function GET() {
  return proxyJson("/api/onboarding/key", "GET", undefined, { cache: "no-store" });
}
