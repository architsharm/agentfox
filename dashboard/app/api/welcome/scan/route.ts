import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/**
 * The welcome page's repository scan. The same gateway call as the Connections
 * tab's Scan button, which posts a form and redirects; this one answers with the
 * scan as JSON so the page can show the result in place, without a reload.
 */
export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  return proxyJson("/api/integrations/github/scan", "POST", {
    repo_full_name: String(body.repo_full_name || ""),
    ref: String(body.ref || ""),
  });
}
