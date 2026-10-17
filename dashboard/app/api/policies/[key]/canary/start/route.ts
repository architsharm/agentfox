import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  const payload = await req.json().catch(() => ({}));
  return proxyJson(`/api/policies/${key}/canary/start`, "POST", payload);
}
