import { proxyJson } from "@/lib/product/proxy";

/**
 * Library actions for the chosen project's agents: `basic/apply`, `starter/remove`,
 * `<library>/apply` and `<library>/mode`, each with `{ agents, mode? }`.
 */
export async function POST(req: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const [library, action] = [path.slice(0, -1).map(encodeURIComponent).join("/"), encodeURIComponent(path[path.length - 1] ?? "")];
  return proxyJson(`/api/policies/libraries/${library}/${action}`, "POST", await req.json().catch(() => ({})));
}
