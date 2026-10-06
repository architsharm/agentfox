import { NextRequest } from "next/server";
import { grantPrincipalKind } from "@/lib/entitlement";
import { proxyCustomBody } from "@/lib/proxy";

/**
 * Custom body rather than the generic Form* helpers: GrantIn.classes is repeated
 * checkbox values, not a single flat field, so formData().getAll() is needed.
 *
 * `principal_kind` is resolved here rather than posted as-is: see
 * lib/entitlement.ts for why a grant to an email address has to be a `subject`.
 */
export async function POST(req: NextRequest) {
  const form = await req.formData();
  const principal = ((form.get("principal") as string) || "").trim();
  const body = {
    resource: ((form.get("resource") as string) || "").trim(),
    principal,
    principal_kind: grantPrincipalKind(principal, form.get("principal_kind") as string | null),
    classes: form.getAll("classes").map(String),
  };

  return proxyCustomBody(req, "POST", "/api/entitlement/grants", "/app/entitlement", body);
}
