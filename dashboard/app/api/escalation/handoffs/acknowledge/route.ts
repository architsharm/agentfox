import { NextRequest, NextResponse } from "next/server";
import { proxyReviewAction } from "@/lib/product/proxy";
import { requestOrigin } from "@/lib/product/origin";

/**
 * "Someone has to act on it" only means something if there is a way to say "I've
 * got this" — otherwise every row in the queue looks perpetually unowned even
 * once a human has actually picked it up.
 */
export async function POST(req: NextRequest) {
  const form = await req.formData();
  const id = String(form.get("id") || "");
  if (!id) {
    const target = new URL("/app/approvals?tab=handoffs", requestOrigin(req));
    target.searchParams.set("review_error", "missing hand-off id");
    return NextResponse.redirect(target);
  }

  return proxyReviewAction(
    req,
    `/api/escalation/handoffs/${encodeURIComponent(id)}/acknowledge`,
    "/app/approvals?tab=handoffs",
    { successNotice: "acknowledged" },
  );
}
