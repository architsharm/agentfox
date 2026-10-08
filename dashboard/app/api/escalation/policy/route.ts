import { NextRequest, NextResponse } from "next/server";
import { proxyCustomBody } from "@/lib/product/proxy";

/**
 * The escalation conditions (turn-depth limit, sentiment threshold, which
 * topics always qualify, etc.) had a working read/write API and no page —
 * every other tuning surface in the product (policy rules, guardrail
 * thresholds) is editable from the dashboard; this one wasn't.
 */
export async function POST(req: NextRequest) {
  const form = await req.formData();
  const owner_role = String(form.get("owner_role") || "support");
  const sla_minutes = Number(form.get("sla_minutes") || 60);
  const mode = String(form.get("mode") || "observe");
  const conditionsRaw = String(form.get("conditions") || "{}");

  let conditions: unknown;
  try {
    conditions = JSON.parse(conditionsRaw);
  } catch {
    const target = new URL("/app/approvals?tab=handoffs", req.nextUrl.origin);
    target.searchParams.set("review_error", "conditions must be valid JSON");
    return NextResponse.redirect(target);
  }

  return proxyCustomBody(
    req,
    "PUT",
    "/api/escalation/policy",
    "/app/approvals?tab=handoffs",
    { conditions, owner_role, sla_minutes, mode },
    { successNotice: "escalation policy saved" },
  );
}
