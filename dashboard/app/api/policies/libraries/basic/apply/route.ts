import { proxyJson } from "@/lib/product/proxy";

/** Apply the basic guardrails to every agent that doesn't have them yet. */
export async function POST() {
  return proxyJson("/api/policies/libraries/basic/apply", "POST", {});
}
