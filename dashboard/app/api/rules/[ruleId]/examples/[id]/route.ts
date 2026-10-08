import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Delete one saved test from a rule. */
export async function DELETE(_req: Request, { params }: { params: Promise<{ ruleId: string; id: string }> }) {
  const { ruleId, id } = await params;
  return proxyJson(`/api/rules/${encodeURIComponent(ruleId)}/examples/${encodeURIComponent(id)}`, "DELETE");
}
