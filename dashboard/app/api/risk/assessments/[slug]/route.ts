import { NextRequest } from "next/server";
import { proxyFormPost } from "@/lib/product/proxy";

export async function POST(req: NextRequest, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return proxyFormPost(req, `/api/risk/assessments/${slug}`, "/app/compliance?tab=risk");
}
