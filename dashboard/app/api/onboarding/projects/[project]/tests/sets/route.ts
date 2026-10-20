import { proxyJson } from "@/lib/product/proxy";

/** The attack sets this project tests with: `{ sets: string[] }`. */
export async function PUT(req: Request, { params }: { params: Promise<{ project: string }> }) {
  const { project } = await params;
  return proxyJson(`/api/onboarding/projects/${encodeURIComponent(project)}/tests/sets`, "PUT", await req.json().catch(() => ({})));
}
