import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Send one sample to a registered model. Records nothing. */
export async function POST(req: NextRequest, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  const { text, surface } = await req.json();
  return proxyJson(`/api/custom-models/${encodeURIComponent(key)}/test`, "POST", {
    text: String(text || ""),
    surface: String(surface || "input"),
  });
}
