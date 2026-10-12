import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** The arguments a tool is known to take, suggested as a value check's field. */
export async function GET(req: NextRequest) {
  const tool = req.nextUrl.searchParams.get("tool") || "";
  return proxyJson(`/api/custom-rules/fields?tool=${encodeURIComponent(tool)}`, "GET");
}
