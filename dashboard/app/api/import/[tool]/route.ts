import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Import another tool's guardrails, leaving out the plan items the user unticked. */
export async function POST(req: NextRequest, { params }: { params: Promise<{ tool: string }> }) {
  const { tool } = await params;
  const { source, skip } = await req.json();
  return proxyJson(`/api/import/${encodeURIComponent(tool)}`, "POST", {
    source: String(source || ""),
    skip: Array.isArray(skip) ? skip.filter((n) => Number.isInteger(n)) : [],
  });
}
