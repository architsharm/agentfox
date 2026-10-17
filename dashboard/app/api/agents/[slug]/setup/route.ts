import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** What one project still needs, for its setup banner; polled while it waits for traffic. */
export async function GET(_req: Request, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return proxyJson(`/api/agents/${encodeURIComponent(slug)}/setup`, "GET", undefined, { cache: "no-store" });
}
