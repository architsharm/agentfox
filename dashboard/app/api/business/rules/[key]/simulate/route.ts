import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Replay recent calls through a business rule as if it enforced; recorded, it lets Start blocking through. */
export async function POST(_req: NextRequest, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  return proxyJson(`/api/business/rules/${encodeURIComponent(key)}/simulate`, "POST", {});
}
