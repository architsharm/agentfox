import { NextRequest, NextResponse } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

const ACTIONS = new Set(["decide", "apply", "rollback", "verify"]);

/** Decide, apply, roll back or verify a suggested change. */
export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string; action: string }> }) {
  const { id, action } = await params;
  if (!ACTIONS.has(action)) return NextResponse.json({ detail: "unknown action" }, { status: 400 });
  const body = await req.json().catch(() => ({}));
  return proxyJson(`/api/proposals/${encodeURIComponent(id)}/${action}`, "POST", body);
}
