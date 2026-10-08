import { NextRequest } from "next/server";
import { proxyFormPatch } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return proxyFormPatch(req, `/api/agents/${slug}`, `/app/agents/${slug}?tab=settings`);
}
