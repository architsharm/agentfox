import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Ask an access check about one example call. Records nothing. */
export async function POST(req: NextRequest, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  const { subject, groups, tool } = await req.json();
  return proxyJson(`/api/authorizers/${encodeURIComponent(key)}/test`, "POST", {
    subject: String(subject || ""),
    groups: Array.isArray(groups) ? groups.map(String) : [],
    tool: String(tool || ""),
  });
}
