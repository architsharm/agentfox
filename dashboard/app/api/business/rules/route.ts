import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Save one compiled business rule, watching. */
export async function POST(req: NextRequest) {
  const { definition, agent } = await req.json();
  return proxyJson("/api/business/rules", "POST", { definition, ...(agent ? { agent } : {}) });
}
