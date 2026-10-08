import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/**
 * Simulate a pack over the last 7 days and record the run. Promotion to enforce
 * requires a recorded simulation of exactly the rules being enforced; the editor's
 * route (../simulate) deliberately does not persist, so this is its recording twin.
 */
export async function POST(req: NextRequest) {
  const { body, agent } = await req.json();
  return proxyJson("/api/policies/simulate", "POST", { body, agent, since_days: 7, persist: true });
}
