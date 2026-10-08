import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** What applying a workspace file would change. Saves nothing. */
export async function POST(req: NextRequest) {
  const { source } = await req.json();
  return proxyJson("/api/workspace/plan", "POST", { source: String(source || "") });
}
