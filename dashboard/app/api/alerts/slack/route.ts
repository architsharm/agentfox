import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Save this workspace's Slack webhook for alerts. */
export async function POST(req: NextRequest) {
  const { url, min_severity } = await req.json();
  return proxyJson("/api/alerts/slack", "PUT", { url, min_severity: min_severity || "medium" });
}

/** Stop sending alerts to Slack. */
export async function DELETE() {
  return proxyJson("/api/alerts/slack", "DELETE");
}
