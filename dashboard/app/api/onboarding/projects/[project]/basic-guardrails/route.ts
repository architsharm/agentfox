import { proxyJson } from "@/lib/product/proxy";

/** Switch on the basic guardrails for every agent in the project. */
export async function POST(_req: Request, { params }: { params: Promise<{ project: string }> }) {
  const { project } = await params;
  return proxyJson(`/api/onboarding/projects/${encodeURIComponent(project)}/basic-guardrails`, "POST", {});
}
