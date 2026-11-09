import { NextRequest } from "next/server";
import { proxyCustomBody, sameOriginPath } from "@/lib/product/proxy";

/**
 * `redirect_to` comes from a hidden field the page itself sets — this route only
 * knows the eval result id from the URL, not which run/suite page the annotate
 * form was opened from.
 */
export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const form = await req.formData();
  const verdict = ((form.get("verdict") as string) || "agree").trim();
  const note = ((form.get("note") as string) || "").trim();
  // A form field, so anyone can post it cross-site: a path on this origin or the default.
  const redirectTo = sameOriginPath(form.get("redirect_to") as string | null, "/app/evals");

  return proxyCustomBody(
    req,
    "POST",
    `/api/eval/results/${id}/annotate`,
    redirectTo,
    { verdict, note },
    { successNotice: "Annotation saved." },
  );
}
