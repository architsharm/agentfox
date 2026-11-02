import { NextRequest } from "next/server";
import { proxyCustomBody } from "@/lib/product/proxy";

/** Release a legal hold from the Retention tab's holds table. */
export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return proxyCustomBody(req, "POST", `/api/legal-holds/${encodeURIComponent(id)}/release`, "/app/settings?tab=retention", {}, {
    successNotice: "Hold released",
  });
}
