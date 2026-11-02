import type { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

/**
 * The setup key for `agentfox init --key`: in full only when just made, its prefix after that.
 * `?peek=1` only reads, so the setup card can show an existing key on load without minting one.
 */
export async function GET(req: NextRequest) {
  const peek = req.nextUrl.searchParams.get("peek") === "1";
  const query = peek ? "?peek=1" : "";
  return proxyJson("/api/onboarding/key" + query, "GET", undefined, { cache: "no-store" });
}
