import { NextRequest } from "next/server";
import { proxyCustomBody } from "@/lib/product/proxy";

/** Release a legal hold from the Retention tab's holds table. */
export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  // The gateway refuses a release without a reason: it lets the purge delete what was kept.
  const form = await req.formData();
  const reason = ((form.get("reason") as string) || "").trim();
  return proxyCustomBody(
    req,
    "POST",
    `/api/legal-holds/${encodeURIComponent(id)}/release`,
    "/app/settings?tab=retention",
    { reason },
    { successNotice: "Hold released" },
  );
}
