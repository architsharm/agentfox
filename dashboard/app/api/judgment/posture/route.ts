import { NextRequest } from "next/server";
import { proxyCustomBody } from "@/lib/proxy";

/**
 * Change the judgment posture — which optional tiers run, and what may leave the box.
 *
 * A plain form POST like the rest of the review actions, not a client component: the
 * whole form is one decision and is submitted as one document. A field-at-a-time API
 * would make each half of a dangerous *combination* look innocuous — a remote tier
 * plus `pii_egress=allow` is a different decision from either alone — and would never
 * show anyone the pair.
 *
 * Whitelisted body rather than forwarding every field, because the form also carries
 * `return_to` and the tier checkboxes arrive as repeated keys that need collecting
 * into a list. `confirm_egress` is forwarded as the boolean the gateway expects: an
 * unchecked HTML checkbox sends nothing at all, which is the correct default here.
 *
 * Session-cookie-only auth comes from `proxyForward` — see lib/proxy.ts. Attributing
 * "who permitted customer data to leave the building" to a dev-fallback identity
 * would corrupt precisely the record this change exists to create.
 */
export async function POST(req: NextRequest) {
  const form = await req.formData();
  const returnTo = String(form.get("return_to") || "/app/policies?tab=guardrails");

  const body = {
    tiers: form.getAll("tiers").map((t) => String(t)),
    pii_egress: String(form.get("pii_egress") || "redact"),
    backend: String(form.get("backend") || "local"),
    // Absent checkbox means unchecked. Failing closed is the safe direction, so an
    // absent value is read as *on*; sending data is not, so an absent value is off.
    fail_closed: form.get("fail_closed") !== null,
    confirm_egress: form.get("confirm_egress") !== null,
    reason: String(form.get("reason") || "").trim(),
  };

  return proxyCustomBody(req, "PUT", "/api/judgment/posture", returnTo, body, {
    successNotice: "judgment posture updated",
  });
}
