import { proxyJson } from "@/lib/product/proxy";

type Ctx = { params: Promise<{ slug: string }> };

/** Run the attack test of the project this agent is in: the same test as its page's panel. */
export async function POST(_req: Request, { params }: Ctx) {
  const { slug } = await params;
  return proxyJson(`/api/onboarding/agents/${encodeURIComponent(slug)}/tests`, "POST", {});
}
