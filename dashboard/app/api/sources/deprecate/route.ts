import { NextRequest, NextResponse } from "next/server";
import { proxyCustomBody } from "@/lib/product/proxy";
import { requestOrigin } from "@/lib/product/origin";

/**
 * Soft-retire a source: `key` travels in the POST body, not the URL path.
 *
 * A source key can itself contain slashes (a URI, a file path), which needs a
 * Next.js catch-all segment to route — but a catch-all folder with static
 * subroutes underneath it (`[...key]/deprecate`, `[...key]/delete`) trips a
 * "Catch-all must be the last part of the URL" error in dev mode. Reading the
 * key from the form body instead sidesteps the whole problem, and matches how
 * the edit/add forms on this page already work.
 */
export async function POST(req: NextRequest) {
  const form = await req.formData();
  const key = String(form.get("key") || "");
  if (!key) {
    const target = new URL("/app/sources", requestOrigin(req));
    target.searchParams.set("review_error", "missing source key");
    return NextResponse.redirect(target);
  }

  return proxyCustomBody(
    req,
    "DELETE",
    `/api/sources/${key.split("/").map(encodeURIComponent).join("/")}`,
    "/app/sources",
    undefined,
  );
}
