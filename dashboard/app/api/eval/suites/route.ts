import { NextRequest } from "next/server";
import { proxyFormPost } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  return proxyFormPost(req, "/api/eval/suites", "/app/evals");
}
