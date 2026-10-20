import { proxyJson } from "@/lib/product/proxy";

/** One run's progress. Polled while it runs. */
export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const id = encodeURIComponent((await params).id);
  return proxyJson(`/api/onboarding/tests/${id}`, "GET", undefined, { cache: "no-store" });
}
