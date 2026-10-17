import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Apply a workspace file. Anything it leaves out is left alone. */
export async function POST(req: NextRequest) {
  const { source } = await req.json();
  return proxyJson("/api/workspace/apply", "POST", { source: String(source || "") });
}
