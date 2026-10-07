import { NextRequest } from "next/server";
import { proxyCustomBody } from "@/lib/product/proxy";

/**
 * "This detection was wrong" — filed from wherever a detection is actually shown
 * (Trace detail), not a separate form nobody would find. Redirects back to
 * whatever page the form was submitted from (return_to), same plain-form-POST
 * pattern as the rest of the review actions. Custom body rather than the generic
 * Form* helpers because the field set is whitelisted, not "every form field" —
 * forwarding everything would also send return_to itself into the API payload.
 */
export async function POST(req: NextRequest) {
  const form = await req.formData();
  const returnTo = String(form.get("return_to") || "/app/policies?tab=guardrails");

  const body: Record<string, string> = {};
  for (const key of ["decision_id", "label", "detector_key", "entity_type", "note"]) {
    const value = form.get(key);
    if (typeof value === "string" && value.trim()) body[key] = value.trim();
  }

  return proxyCustomBody(req, "POST", "/api/guardrails/feedback", returnTo, body, {
    successNotice: "feedback recorded",
  });
}
