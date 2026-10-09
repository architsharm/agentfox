import { NextRequest } from "next/server";
import { proxyCustomBody, proxyJson, sameOriginPath } from "@/lib/product/proxy";

/**
 * The same whole-document write, as JSON, for the Checks screen's tier switches.
 * The switch sends the full posture with one tier changed, so the gateway still sees
 * (and refuses or asks to confirm) the combination, never half of it.
 */
export async function PUT(req: NextRequest) {
  const b = await req.json();
  return proxyJson("/api/judgment/posture", "PUT", {
    tiers: Array.isArray(b.tiers) ? b.tiers.map(String) : [],
    pii_egress: String(b.pii_egress || "redact"),
    backend: String(b.backend || "local"),
    fail_closed: b.fail_closed !== false,
    confirm_egress: b.confirm_egress === true,
    reason: String(b.reason || "").trim(),
  });
}

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
 * Session-cookie-only auth comes from `proxyForward` — see lib/product/proxy.ts. Attributing
 * "who permitted customer data to leave the building" to a dev-fallback identity
 * would corrupt precisely the record this change exists to create.
 */
export async function POST(req: NextRequest) {
  const form = await req.formData();
  const returnTo = sameOriginPath(form.get("return_to") as string | null, "/app/policies?tab=advanced&sec=tuning");

  const body = {
    tiers: form.getAll("tiers").map((t) => String(t)),
    pii_egress: String(form.get("pii_egress") || "redact"),
    backend: String(form.get("backend") || "local"),
    // An unchecked HTML checkbox sends nothing, so absent means off for both. The
    // safe default for fail_closed comes from the form, not from here: the box is
    // rendered checked, and when the deployment requires failing closed it is
    // disabled and a hidden `fail_closed=on` is posted in its place
    // (components/product/JudgmentPosture.tsx). An unticked box is a deliberate choice to
    // fail open, and the gateway refuses it if the deployment does not allow that.
    fail_closed: form.get("fail_closed") !== null,
    confirm_egress: form.get("confirm_egress") !== null,
    reason: String(form.get("reason") || "").trim(),
  };

  return proxyCustomBody(req, "PUT", "/api/judgment/posture", returnTo, body, {
    successNotice: "judgment posture updated",
  });
}
