import { proxyJson } from "@/lib/product/proxy";

/** What `agentfox init` reported. Connect polls this every 2 seconds. */
export async function GET() {
  return proxyJson("/api/onboarding/structure", "GET", undefined, { cache: "no-store" });
}

/** Save the map after the user added or removed an agent or tool. */
export async function PUT(req: Request) {
  return proxyJson("/api/onboarding/structure", "PUT", await req.json().catch(() => ({})));
}
