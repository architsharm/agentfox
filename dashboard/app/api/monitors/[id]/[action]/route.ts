import { NextResponse } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

const ACTIONS = new Set(["run", "pause", "resume"]);

export async function POST(_req: Request, { params }: { params: Promise<{ id: string; action: string }> }) {
  const { id, action } = await params;
  if (!ACTIONS.has(action)) return NextResponse.json({ detail: "unknown action" }, { status: 400 });
  return proxyJson(`/api/monitors/${encodeURIComponent(id)}/${action}`, "POST");
}
