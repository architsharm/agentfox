import { NextRequest, NextResponse } from "next/server";
import { proxyCustomBody } from "@/lib/product/proxy";
import { requestOrigin } from "@/lib/product/origin";
import { appReturnPath, controlNotice, type ControlAction } from "@/lib/product/agentStatus";

const ACTIONS = new Set<ControlAction>(["quarantine", "kill", "resume"]);

/**
 * One route for all three transitions (pause = `quarantine`, stop = `kill`, resume) —
 * same shape (`reason` in the body, `POST /api/agents/{slug}/{action}` on the
 * backend), just a different action per form's hidden field.
 *
 * Afterwards the browser goes back to the page it was on: the form's `return_to`,
 * else the Referer, as long as it is an in-app page on this origin; else the agent's
 * page. Pausing from the canvas leaves you on the canvas.
 */
export async function POST(req: NextRequest, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const form = await req.formData();
  const origin = requestOrigin(req);
  const fallback = `/app/projects/${encodeURIComponent(slug)}`;
  const back = appReturnPath(
    (form.get("return_to") as string | null) || req.headers.get("referer"),
    origin,
    fallback,
  );
  const action = String(form.get("action") || "") as ControlAction;
  if (!ACTIONS.has(action)) {
    const target = new URL(back, origin);
    target.searchParams.set("review_error", "invalid control action");
    return NextResponse.redirect(target, 303);
  }
  const reason = String(form.get("reason") || "").trim();

  return proxyCustomBody(req, "POST", `/api/agents/${encodeURIComponent(slug)}/${action}`, back, { reason }, {
    successNotice: controlNotice(action, String(form.get("name") || "")),
  });
}
