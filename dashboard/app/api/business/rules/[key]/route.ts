import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Change a business rule's thresholds in place (it keeps its mode). */
export async function PUT(req: NextRequest, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  const { definition } = await req.json();
  return proxyJson(`/api/business/rules/${encodeURIComponent(key)}`, "PUT", { definition: definition || {} });
}

/** Delete a business rule. */
export async function DELETE(_req: Request, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  return proxyJson(`/api/business/rules/${encodeURIComponent(key)}`, "DELETE");
}
