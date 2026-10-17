import { NextRequest } from "next/server";
import { proxyReviewAction } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  return proxyReviewAction(req, "/api/controls/compute", "/app/compliance");
}
