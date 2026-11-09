import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Compile written policy into rules and questions. Saves nothing. `agent` lets the
 * compiler resolve tool names against that agent's declared tools; `tool`, picked in
 * the form, is the tool the limit governs. */
export async function POST(req: NextRequest) {
  const { text, agent, tool } = await req.json();
  return proxyJson("/api/business/compile", "POST", { text, ...(agent ? { agent } : {}), ...(tool ? { tool } : {}) });
}
