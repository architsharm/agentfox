import { proxyJson } from "@/lib/product/proxy";

/** A new setup key, shown in full this once; the old one stops being accepted. */
export async function POST() {
  return proxyJson("/api/onboarding/key/rotate", "POST", undefined, { cache: "no-store" });
}
