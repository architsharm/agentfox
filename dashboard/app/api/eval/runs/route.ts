import { NextRequest } from "next/server";
import { proxyCustomBody } from "@/lib/product/proxy";

/**
 * Custom body rather than the generic Form* helpers: RunIn.target is its own JSON
 * object (agent/provider/model) and scorers is a list built from repeated
 * checkboxes, neither of which the flat form-to-JSON helper produces.
 */
export async function POST(req: NextRequest) {
  const form = await req.formData();
  const suite = (form.get("suite") as string) || "";
  const agent = ((form.get("agent") as string) || "").trim();
  const provider = ((form.get("provider") as string) || "echo").trim();
  const model = ((form.get("model") as string) || "echo-1").trim();
  const scorers = form.getAll("scorers") as string[];

  const body = {
    suite,
    target: { ...(agent ? { agent } : {}), provider, model },
    scorers: scorers.length ? scorers : null,
  };

  return proxyCustomBody(req, "POST", "/api/eval/runs", `/app/evals/${suite}`, body);
}
