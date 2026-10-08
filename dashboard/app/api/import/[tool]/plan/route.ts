import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** What importing another tool's guardrails would do. Saves nothing. */
export async function POST(req: NextRequest, { params }: { params: Promise<{ tool: string }> }) {
  const { tool } = await params;
  const { source } = await req.json();
  return proxyJson(`/api/import/${encodeURIComponent(tool)}/plan`, "POST", { source: String(source || "") });
}
