import { proxyJson } from "@/lib/product/proxy";

/** Basic guardrails picked from the agent's map; POST saves the choices. */
export async function GET() {
  return proxyJson("/api/onboarding/guardrails", "GET", undefined, { cache: "no-store" });
}

export async function POST(req: Request) {
  return proxyJson("/api/onboarding/guardrails", "POST", await req.json().catch(() => []));
}
