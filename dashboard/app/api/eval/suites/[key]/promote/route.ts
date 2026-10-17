import { NextRequest, NextResponse } from "next/server";
import { proxyReviewAction } from "@/lib/product/proxy";
import { requestOrigin } from "@/lib/product/origin";

export async function POST(req: NextRequest, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  const form = await req.formData();
  const traceId = ((form.get("trace_id") as string) || "").trim();
  if (!traceId) {
    const target = new URL(`/app/evals/${key}`, requestOrigin(req));
    target.searchParams.set("review_error", "trace id is required");
    return NextResponse.redirect(target);
  }

  return proxyReviewAction(
    req,
    `/api/eval/suites/${key}/cases/from-trace?trace_id=${encodeURIComponent(traceId)}`,
    `/app/evals/${key}`,
  );
}
