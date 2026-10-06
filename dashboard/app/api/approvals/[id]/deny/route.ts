import { NextRequest } from "next/server";
import { proxyCustomBody } from "@/lib/product/proxy";

export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const form = await req.formData();
  const rationale = String(form.get("rationale") || "");
  return proxyCustomBody(
    req,
    "POST",
    `/api/approvals/${encodeURIComponent(id)}/deny`,
    "/app/approvals",
    { rationale },
    { successNotice: "denied" },
  );
}
