import { NextRequest, NextResponse } from "next/server";
import { proxyRedirectWithHandler } from "@/lib/product/proxy";

/**
 * Fetches the source's actual content and hashes it against what was last
 * recorded — the difference between "this source is tiered" (a human's claim)
 * and "we went and checked" (see /sources/page.tsx).
 *
 * `key` travels in the POST body rather than the URL path — see
 * deprecate/route.ts for why.
 */
export async function POST(req: NextRequest) {
  const form = await req.formData();
  const key = String(form.get("key") || "");
  if (!key) {
    const target = new URL("/app/sources", req.nextUrl.origin);
    target.searchParams.set("review_error", "missing source key");
    return NextResponse.redirect(target);
  }

  return proxyRedirectWithHandler(
    req,
    "POST",
    `/api/sources/${key.split("/").map(encodeURIComponent).join("/")}/validate`,
    "/app/sources",
    undefined,
    (res, body) => {
      if (!res.ok) return { error: body.detail || res.statusText };
      if (body.status === "changed") {
        return { notice: `${key}: content changed since it was last validated` };
      }
      if (body.status === "unreachable") {
        return { error: `${key}: ${body.reason || "could not be fetched"}` };
      }
      return {};
    },
  );
}
