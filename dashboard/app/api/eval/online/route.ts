import { NextRequest } from "next/server";
import { proxyRedirectWithHandler } from "@/lib/product/proxy";

/**
 * Scores already-recorded production traces for an agent with the same scorers an
 * offline suite uses — the only way to get a real (not echo-synthesised) pass rate
 * without a live model call, since NativeEvalRunner's offline path calls a
 * configured provider directly and has no route to a specific deployed agent's own
 * tools. See sample_production() in evaluation/runner.py.
 */
export async function POST(req: NextRequest) {
  const form = await req.formData();
  const agent = ((form.get("agent") as string) || "").trim();
  const since_days = Number(form.get("since_days")) || 7;
  const rate = Number(form.get("rate")) || 1;

  return proxyRedirectWithHandler(
    req,
    "POST",
    "/api/eval/online",
    "/app/test?tab=reliability",
    { agent, since_days, rate },
    (res, body) => {
      if (!res.ok) return { error: body.detail || res.statusText };
      if (!body.summary) {
        return { notice: `No production traffic for '${agent}' in the last ${since_days} day(s) to sample.` };
      }
      return { notice: `Sampled ${body.summary.cases} recent trace(s) from '${agent}' and scored them.` };
    },
  );
}
