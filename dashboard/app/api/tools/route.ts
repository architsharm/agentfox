import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/**
 * Every registered tool. The custom-rule condition editor (ConditionFields) offers
 * these as the tool to match; without this route its request 404'd and the picker
 * was silently empty.
 */
export async function GET() {
  return proxyJson("/api/tools", "GET", undefined, { cache: "no-store" });
}
