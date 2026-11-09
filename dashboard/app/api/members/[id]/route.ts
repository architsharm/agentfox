import { proxyJson } from "@/lib/product/proxy";

/** Change a teammate's role, or deactivate them: `{ role }` or `{ active }`. */
export async function PATCH(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await req.json().catch(() => ({}));
  return proxyJson(`/api/members/${encodeURIComponent(id)}`, "PATCH", { role: body?.role, active: body?.active });
}
