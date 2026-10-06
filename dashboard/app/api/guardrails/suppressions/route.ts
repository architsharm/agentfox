import { NextRequest } from "next/server";
import { proxyCustomBody } from "@/lib/product/proxy";

/**
 * Accept a filed false positive as a scoped, expiring exception. Only reachable
 * from a `false_positive` feedback row (see the Guardrail tuning tab on
 * /policies) — the backend itself rejects any other label, this just keeps the
 * form from being offered at all.
 */
export async function POST(req: NextRequest) {
  const form = await req.formData();
  const body: Record<string, unknown> = {};
  for (const key of ["feedback_id", "scope", "reason"]) {
    const value = form.get(key);
    if (typeof value === "string" && value.trim()) body[key] = value.trim();
  }
  const ttlDays = form.get("ttl_days");
  if (typeof ttlDays === "string" && ttlDays.trim()) body.ttl_days = Number(ttlDays);
  body.exact = form.get("exact") === "on";

  return proxyCustomBody(req, "POST", "/api/guardrails/suppressions", "/app/policies?tab=guardrails", body, {
    successNotice: "suppression created",
  });
}
