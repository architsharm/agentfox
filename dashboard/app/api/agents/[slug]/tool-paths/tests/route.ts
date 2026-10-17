import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Add a production tool path to a test suite, as a case that expects it. */
export async function POST(req: NextRequest, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const body = await req.json().catch(() => ({}));
  return proxyJson(`/api/agents/${encodeURIComponent(slug)}/tool-paths/tests`, "POST", {
    path: Array.isArray(body.path) ? body.path.map(String) : [],
    trace_id: body.trace_id ? String(body.trace_id) : null,
    suite: body.suite ? String(body.suite) : "regressions",
  });
}
