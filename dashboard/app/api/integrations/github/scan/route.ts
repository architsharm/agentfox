/**
 * Proxies a scan trigger from a plain HTML form (no client JS) to the gateway,
 * then redirects back to the Connect page with the result in the query string —
 * the gateway does all the actual work (download, static scan, draft creation).
 */

import { NextRequest, NextResponse } from "next/server";
import { proxyRedirectWithHandler } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const form = await req.formData();
  const repo_full_name = String(form.get("repo_full_name") || "");
  const ref = String(form.get("ref") || "");

  if (!repo_full_name) {
    const target = new URL("/app/start?tab=connect", req.nextUrl.origin);
    target.searchParams.set("scan_error", "missing repository or session");
    return NextResponse.redirect(target);
  }

  return proxyRedirectWithHandler(
    req,
    "POST",
    "/api/integrations/github/scan",
    "/app/start?tab=connect",
    { repo_full_name, ref },
    (res, body) =>
      res.ok
        ? { extra: { scan_run_id: body.scan_run_id } }
        : { error: body.detail || res.statusText },
    { errorParam: "scan_error" },
  );
}
