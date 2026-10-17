import { NextRequest, NextResponse } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Get started, step 1: register an agent and stay on the page (JSON, not a redirect). */
export async function POST(req: NextRequest) {
  const { slug, name } = await req.json().catch(() => ({}));
  if (!slug || typeof slug !== "string") return NextResponse.json({ detail: "an agent id is required" }, { status: 400 });
  return proxyJson("/api/agents", "POST", { slug, name: typeof name === "string" ? name : slug });
}
