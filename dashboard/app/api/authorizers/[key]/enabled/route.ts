import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  const { enabled, reason } = await req.json();
  return proxyJson(`/api/authorizers/${encodeURIComponent(key)}/enabled`, "POST", {
    enabled: Boolean(enabled),
    reason: String(reason || ""),
  });
}
