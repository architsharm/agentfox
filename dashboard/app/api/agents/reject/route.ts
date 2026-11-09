import { proxyJson } from "@/lib/product/proxy";

/** Dismiss several proposed agents at once: `{ ids: [...] }` ("Dismiss all" on Proposed). */
export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  return proxyJson("/api/agents/reject", "POST", { ids: Array.isArray(body?.ids) ? body.ids : [] });
}
