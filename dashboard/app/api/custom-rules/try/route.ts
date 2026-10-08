import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Match a sample text against an unsaved rule. Records nothing. */
export async function POST(req: NextRequest) {
  const { rule, text, surface } = await req.json();
  return proxyJson("/api/custom-rules/try", "POST", { rule, text: String(text || ""), surface: surface || "input" });
}
