import { NextRequest, NextResponse } from "next/server";
import { proxyCustomBody } from "@/lib/product/proxy";

const ACTIONS = new Set(["quarantine", "kill", "resume"]);
const PAST: Record<string, string> = { quarantine: "quarantined", kill: "killed", resume: "resumed" };

/**
 * One route for all three transitions (quarantine/kill/resume) — same shape
 * (`reason` in the body, `POST /api/agents/{slug}/{action}` on the backend),
 * just a different action per form's hidden field.
 */
export async function POST(req: NextRequest, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const form = await req.formData();
  const action = String(form.get("action") || "");
  if (!ACTIONS.has(action)) {
    const target = new URL(`/app/agents/${slug}`, req.nextUrl.origin);
    target.searchParams.set("review_error", "invalid control action");
    return NextResponse.redirect(target);
  }
  const reason = String(form.get("reason") || "");

  return proxyCustomBody(
    req,
    "POST",
    `/api/agents/${encodeURIComponent(slug)}/${action}`,
    `/app/agents/${slug}`,
    { reason },
    { successNotice: `agent ${PAST[action]}` },
  );
}
