import { proxyJson } from "@/lib/product/proxy";

/** Start a test run: `{ phase: "before" | "after" }`. The connected runner picks it up. */
export async function POST(req: Request) {
  return proxyJson("/api/onboarding/tests", "POST", await req.json().catch(() => ({})));
}

/** The latest run for a phase, or null. */
export async function GET(req: Request) {
  const phase = new URL(req.url).searchParams.get("phase") === "after" ? "after" : "before";
  return proxyJson(`/api/onboarding/tests?phase=${phase}`, "GET", undefined, { cache: "no-store" });
}
