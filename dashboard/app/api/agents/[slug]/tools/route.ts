import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** One agent's tools (granted, in its code, or seen called), for the Test page's tool picker. */
export async function GET(_req: Request, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return proxyJson(`/api/agents/${encodeURIComponent(slug)}/tools`, "GET", undefined, { cache: "no-store" });
}
