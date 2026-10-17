import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Register (or update) a classifier endpoint the workspace runs itself. */
export async function POST(req: NextRequest) {
  return proxyJson("/api/custom-models", "POST", await req.json());
}
