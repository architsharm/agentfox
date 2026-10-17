import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Compile written policy into rules and questions. Saves nothing. */
export async function POST(req: NextRequest) {
  const { text } = await req.json();
  return proxyJson("/api/business/compile", "POST", { text });
}
