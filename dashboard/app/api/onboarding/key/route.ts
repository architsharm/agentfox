import { proxyJson } from "@/lib/product/proxy";

/** The setup key for `agentfox init --key`: in full only when just made, its prefix after that. */
export async function GET() {
  return proxyJson("/api/onboarding/key", "GET", undefined, { cache: "no-store" });
}
