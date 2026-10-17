import { NextRequest } from "next/server";
import { proxyCustomBody } from "@/lib/product/proxy";

/**
 * Custom body rather than the generic Form* helpers: EvalCase.input/expected/context
 * are each their own JSON object server-side (CaseIn in evaluation.py), not flat
 * fields, so the form's prompt/goal/retrieved inputs need reshaping before they're
 * forwarded.
 */
export async function POST(req: NextRequest, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  const form = await req.formData();
  const prompt = ((form.get("prompt") as string) || "").trim();
  const goal = ((form.get("goal") as string) || "").trim();
  const retrieved = ((form.get("retrieved") as string) || "").trim();

  const body = {
    input: { prompt },
    expected: goal ? { goal } : {},
    context: retrieved ? { retrieved: retrieved.split("\n").filter(Boolean) } : {},
    split: "test",
  };

  return proxyCustomBody(req, "POST", `/api/eval/suites/${key}/cases`, `/app/evals/${key}`, body);
}
