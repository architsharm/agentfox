import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const { text, chunks, source_key } = await req.json();
  return proxyJson("/api/sources/context-check", "POST", {
    text: text || "",
    chunks: chunks || [],
    source_key: source_key || "",
  });
}
