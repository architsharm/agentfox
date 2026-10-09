import { NextRequest } from "next/server";
import { proxyCustomBody } from "@/lib/product/proxy";

/** Record an attestation of one control against one framework, then return to it. */
export async function POST(req: NextRequest, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  const form = await req.formData();
  const framework = ((form.get("framework") as string) || "").trim();
  const outcome = ((form.get("outcome") as string) || "").trim();
  const note = ((form.get("note") as string) || "").trim();
  const back = `/app/compliance/controls/${encodeURIComponent(key)}?framework=${encodeURIComponent(framework)}`;
  return proxyCustomBody(
    req,
    "POST",
    `/api/controls/${encodeURIComponent(key)}/reviews`,
    back,
    { framework, outcome, note },
    { successNotice: "Review recorded." },
  );
}
