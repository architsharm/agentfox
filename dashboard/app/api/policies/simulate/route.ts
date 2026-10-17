import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const { body, agent } = await req.json();
  return proxyJson("/api/policies/simulate", "POST", { body, agent, persist: false });
}
