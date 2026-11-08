import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Make an earlier version of a pack live again, as a new version in the pack's current mode. */
export async function POST(_req: NextRequest, { params }: { params: Promise<{ key: string; version: string }> }) {
  const { key, version } = await params;
  return proxyJson(`/api/policies/${encodeURIComponent(key)}/versions/${encodeURIComponent(version)}/restore`, "POST", {});
}
