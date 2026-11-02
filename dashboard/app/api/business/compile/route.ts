import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Compile written policy into rules and questions. Saves nothing. `agent` lets the
 * compiler resolve tool names against that agent's declared tools. */
export async function POST(req: NextRequest) {
  const { text, agent } = await req.json();
  return proxyJson("/api/business/compile", "POST", { text, ...(agent ? { agent } : {}) });
}
