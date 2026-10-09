import { NextRequest } from "next/server";
import { proxyCustomBody } from "@/lib/product/proxy";

/** Change how long one data class is kept. The gateway audits it and checks the role. */
export async function POST(req: NextRequest, { params }: { params: Promise<{ dataClass: string }> }) {
  const { dataClass } = await params;
  const form = await req.formData();
  const retain_days = Number(form.get("retain_days"));
  const reason = ((form.get("reason") as string) || "").trim();
  return proxyCustomBody(
    req,
    "PUT",
    `/api/retention/${encodeURIComponent(dataClass)}`,
    "/app/compliance?tab=retention",
    { retain_days, reason },
    { successNotice: "Retention updated." },
  );
}
