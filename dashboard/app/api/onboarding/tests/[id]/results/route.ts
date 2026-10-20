import { proxyJson } from "@/lib/product/proxy";

/** Every attack in a run with its outcome: the full report. */
export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const id = encodeURIComponent((await params).id);
  return proxyJson(`/api/onboarding/tests/${id}/results`, "GET", undefined, { cache: "no-store" });
}
