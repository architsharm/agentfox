import { NextRequest } from "next/server";
import { proxyFormPatch } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return proxyFormPatch(req, `/api/findings/${id}`, `/app/findings/${id}`);
}
