import { NextRequest } from "next/server";
import { proxyRedirectWithHandler } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Run the retention purge now and say what it removed. */
export async function POST(req: NextRequest) {
  return proxyRedirectWithHandler(req, "POST", "/api/retention/purge", "/app/compliance?tab=retention", undefined, (res, body) => {
    if (!res.ok) return { error: body.detail || res.statusText };
    let deleted = 0;
    let redacted = 0;
    for (const r of Object.values<any>(body.run?.results || {})) {
      for (const [k, v] of Object.entries<any>(r)) {
        if (typeof v !== "number") continue;
        if (k.endsWith("_deleted")) deleted += v;
        if (k.endsWith("_redacted")) redacted += v;
      }
    }
    return { notice: `Purge done: ${deleted} deleted, ${redacted} redacted.` };
  });
}
