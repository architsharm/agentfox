import { NextRequest } from "next/server";
import { proxyCustomBody, sameOriginPath } from "@/lib/product/proxy";

export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const form = await req.formData();
  const rationale = String(form.get("rationale") || "");
  return proxyCustomBody(
    req,
    "POST",
    `/api/approvals/${encodeURIComponent(id)}/approve`,
    // Home approves inline too, and should land back on Home rather than here.
    sameOriginPath(form.get("return_to") as string | null, "/app/approvals"),
    { rationale },
    { successNotice: "approved" },
  );
}
