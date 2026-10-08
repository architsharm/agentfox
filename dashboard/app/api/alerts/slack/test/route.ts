import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

export async function POST() {
  return proxyJson("/api/alerts/slack/test", "POST");
}
