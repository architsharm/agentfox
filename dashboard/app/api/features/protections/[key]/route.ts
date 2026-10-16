import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Set a protection for every project, or (with `agent`) for one. */
export async function POST(req: NextRequest, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  const { level, agent, open_to_projects, reason } = await req.json();
  return proxyJson(`/api/features/protections/${encodeURIComponent(key)}`, "POST", {
    level: level ?? null,
    agent: String(agent || ""),
    open_to_projects: typeof open_to_projects === "boolean" ? open_to_projects : null,
    reason: String(reason || ""),
  });
}
