import { proxyJson } from "@/lib/product/proxy";

/** Every attack test the projects ran, latest first; with `?agent=`, the runs that tested it. */
export async function GET(req: Request) {
  const agent = new URL(req.url).searchParams.get("agent");
  const query = agent ? `?agent=${encodeURIComponent(agent)}` : "";
  return proxyJson(`/api/onboarding/runs${query}`, "GET", undefined, { cache: "no-store" });
}
