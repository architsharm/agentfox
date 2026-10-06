/**
 * Same plain-HTML-form-POST-no-client-JS proxy pattern as
 * api/integrations/github/scan/route.ts, for the second onboarding path: a hosted
 * API endpoint plus its docs, instead of repo access.
 */

import { NextRequest, NextResponse } from "next/server";
import { proxyRedirectWithHandler } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const form = await req.formData();
  const endpoint_url = String(form.get("endpoint_url") || "");
  const docs_url = String(form.get("docs_url") || "");
  const openapi_spec_url = String(form.get("openapi_spec_url") || "");
  const purpose = String(form.get("purpose") || "");

  if (!endpoint_url) {
    const target = new URL("/app/start?tab=connect", req.nextUrl.origin);
    target.searchParams.set("scan_error", "missing endpoint URL or session");
    return NextResponse.redirect(target);
  }

  return proxyRedirectWithHandler(
    req,
    "POST",
    "/api/integrations/hosted-api/scan",
    "/app/start?tab=connect",
    { endpoint_url, docs_url: docs_url || null, openapi_spec_url: openapi_spec_url || null, purpose },
    (res, body) =>
      res.ok
        ? { extra: { hosted_scan_run_id: body.scan_run_id } }
        : { error: body.detail || res.statusText },
    { errorParam: "scan_error" },
  );
}
