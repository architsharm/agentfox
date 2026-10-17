import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Register (or update) the workspace's own access-check endpoint. */
export async function POST(req: NextRequest) {
  return proxyJson("/api/authorizers", "POST", await req.json());
}
