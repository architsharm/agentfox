import { proxyJson } from "@/lib/product/proxy";

type Ctx = { params: Promise<{ project: string }> };

/** The project's first attack test and its latest with the basic guardrails. */
export async function GET(_req: Request, { params }: Ctx) {
  const { project } = await params;
  return proxyJson(`/api/onboarding/projects/${encodeURIComponent(project)}/tests`, "GET", undefined, { cache: "no-store" });
}

/** Test the project again, with the guardrails it has now. */
export async function POST(_req: Request, { params }: Ctx) {
  const { project } = await params;
  return proxyJson(`/api/onboarding/projects/${encodeURIComponent(project)}/tests`, "POST", {});
}
