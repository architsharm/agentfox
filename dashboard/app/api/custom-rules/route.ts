import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

const FIELDS = [
  "key", "name", "kind", "polarity", "entries", "examples", "description", "surfaces", "agents",
  "case_sensitive", "sequence", "condition", "validator", "enabled", "effect", "message", "on_block", "severity",
] as const;

/** Save a rule in the customer's own words: words, patterns, a topic, a sequence, a value
 * check or a built-in check. A field missing from FIELDS never reaches the gateway, which
 * is how value checks were being saved without their condition. */
export async function POST(req: NextRequest) {
  const body = await req.json();
  return proxyJson("/api/custom-rules", "POST", Object.fromEntries(FIELDS.filter((f) => f in body).map((f) => [f, body[f]])));
}
