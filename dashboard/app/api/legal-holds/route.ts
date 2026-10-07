import { NextRequest } from "next/server";
import { proxyCustomBody } from "@/lib/product/proxy";

/**
 * Custom body rather than the generic Form* helpers: the backend's LegalHoldIn.scope
 * is its own JSON object (`{agents: [...]}`), not a flat form field, so the form's
 * comma-separated agents text needs folding into it before forwarding.
 */
export async function POST(req: NextRequest) {
  const form = await req.formData();
  const reason = ((form.get("reason") as string) || "").trim();
  const agents = ((form.get("agents") as string) || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  const scope: Record<string, unknown> = {};
  if (agents.length) scope.agents = agents;

  return proxyCustomBody(req, "POST", "/api/legal-holds", "/app/compliance?tab=retention", {
    scope,
    reason,
  });
}
