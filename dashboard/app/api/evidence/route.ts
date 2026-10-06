import { NextRequest } from "next/server";
import { proxyCustomBody } from "@/lib/product/proxy";

/**
 * Custom body rather than the generic Form* helpers: EvidenceIn.agents/controls
 * are each their own array server-side, not flat strings, so the form's
 * comma-separated text inputs need splitting before they're forwarded. Blank date
 * fields are dropped rather than sent as "" so the backend's own "*"/unbounded
 * defaults apply.
 */
export async function POST(req: NextRequest) {
  const form = await req.formData();
  const split = (name: string) =>
    ((form.get(name) as string) || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  const dateField = (name: string) => {
    const raw = (form.get(name) as string) || "";
    return raw ? new Date(raw).toISOString() : undefined;
  };

  const body: Record<string, unknown> = {};
  const agents = split("agents");
  const controls = split("controls");
  if (agents.length) body.agents = agents;
  if (controls.length) body.controls = controls;
  const periodFrom = dateField("period_from");
  const periodTo = dateField("period_to");
  if (periodFrom) body.period_from = periodFrom;
  if (periodTo) body.period_to = periodTo;

  return proxyCustomBody(req, "POST", "/api/evidence", "/app/compliance?tab=evidence", body);
}
