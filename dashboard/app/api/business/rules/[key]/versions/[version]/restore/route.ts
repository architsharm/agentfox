import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Put an earlier version of a business rule back, as a new version in its current mode. */
export async function POST(_req: NextRequest, { params }: { params: Promise<{ key: string; version: string }> }) {
  const { key, version } = await params;
  return proxyJson(`/api/business/rules/${encodeURIComponent(key)}/versions/${encodeURIComponent(version)}/restore`, "POST", {});
}
