import { proxyJson } from "@/lib/product/proxy";

/** Remove the watch-only starter rules earlier versions of `agentfox init` added. */
export async function POST() {
  return proxyJson("/api/policies/libraries/starter/remove", "POST", {});
}
