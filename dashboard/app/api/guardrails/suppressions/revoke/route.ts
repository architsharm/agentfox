import { NextRequest, NextResponse } from "next/server";
import { proxyCustomBody } from "@/lib/product/proxy";
import { requestOrigin } from "@/lib/product/origin";

export async function POST(req: NextRequest) {
  const form = await req.formData();
  const id = String(form.get("id") || "");
  if (!id) {
    const target = new URL("/app/policies?tab=changes", requestOrigin(req));
    target.searchParams.set("review_error", "missing suppression id");
    return NextResponse.redirect(target);
  }

  return proxyCustomBody(
    req,
    "DELETE",
    `/api/guardrails/suppressions/${encodeURIComponent(id)}`,
    "/app/policies?tab=changes",
    undefined,
    { successNotice: "suppression revoked" },
  );
}
