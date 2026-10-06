import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/proxy";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  const { mode, version, level, scope_id, compose } = await req.json();
  return proxyJson(`/api/policies/${key}/mode`, "POST", {
    mode,
    ...(version != null ? { version } : {}),
    ...(level ? { level } : {}),
    ...(scope_id ? { scope_id } : {}),
    ...(compose ? { compose } : {}),
  });
}
