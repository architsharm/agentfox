import { NextRequest } from "next/server";
import { proxyFormPost } from "@/lib/product/proxy";

export async function POST(req: NextRequest) {
  return proxyFormPost(req, "/api/frameworks/review", "/app/compliance?tab=frameworks");
}
