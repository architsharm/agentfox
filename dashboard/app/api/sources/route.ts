import { NextRequest } from "next/server";
import { proxyFormPut } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  return proxyFormPut(req, "/api/sources", "/app/sources");
}
