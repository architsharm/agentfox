import { NextRequest } from "next/server";
import { proxyCustomBody } from "@/lib/product/proxy";

/**
 * Custom body rather than the generic Form* helpers: PrincipalIn.groups/clearances
 * are each their own array server-side, not flat strings, so the form's
 * comma-separated text inputs need splitting before they're forwarded.
 */
export async function POST(req: NextRequest) {
  const form = await req.formData();
  const split = (name: string) =>
    ((form.get(name) as string) || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);

  const body = {
    subject: ((form.get("subject") as string) || "").trim(),
    display: ((form.get("display") as string) || "").trim(),
    groups: split("groups"),
    clearances: split("clearances"),
  };

  return proxyCustomBody(req, "PUT", "/api/entitlement/principals", "/app/entitlement", body);
}
