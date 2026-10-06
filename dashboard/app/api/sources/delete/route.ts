import { NextRequest, NextResponse } from "next/server";
import { proxyCustomBody } from "@/lib/product/proxy";

/**
 * Hard delete (?hard=true) — irreversible, only ever offered on an already-
 * deprecated source in the UI (see /sources/page.tsx). Removes the record
 * entirely rather than keeping the "retired because it was wrong" signal.
 *
 * `key` travels in the POST body rather than the URL path — see deprecate/route.ts
 * for why (a catch-all route segment with static subroutes under it breaks
 * Next.js dev mode).
 */
export async function POST(req: NextRequest) {
  const form = await req.formData();
  const key = String(form.get("key") || "");
  if (!key) {
    const target = new URL("/app/sources", req.nextUrl.origin);
    target.searchParams.set("review_error", "missing source key");
    return NextResponse.redirect(target);
  }

  return proxyCustomBody(
    req,
    "DELETE",
    `/api/sources/${key.split("/").map(encodeURIComponent).join("/")}?hard=true`,
    "/app/sources",
    undefined,
  );
}
