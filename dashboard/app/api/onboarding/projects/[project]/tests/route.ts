import { proxyJson } from "@/lib/product/proxy";

type Ctx = { params: Promise<{ project: string }> };

/** The project's first attack test and its latest with the basic guardrails; with `?agent=`, as that agent saw them. */
export async function GET(req: Request, { params }: Ctx) {
  const { project } = await params;
  const agent = new URL(req.url).searchParams.get("agent");
  const query = agent ? `?agent=${encodeURIComponent(agent)}` : "";
  return proxyJson(`/api/onboarding/projects/${encodeURIComponent(project)}/tests${query}`, "GET", undefined, { cache: "no-store" });
}

/** Test the project again, with the guardrails it has now. */
export async function POST(_req: Request, { params }: Ctx) {
  const { project } = await params;
  return proxyJson(`/api/onboarding/projects/${encodeURIComponent(project)}/tests`, "POST", {});
}
