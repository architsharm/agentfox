import { NextRequest } from "next/server";
import { proxyCustomBody } from "@/lib/product/proxy";

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
  const redirectTo = (form.get("redirect_to") as string) || "/app/evals";

  return proxyCustomBody(
    req,
    "POST",
    `/api/eval/results/${id}/annotate`,
    redirectTo,
    { verdict, note },
    { successNotice: "Annotation saved." },
  );
}
