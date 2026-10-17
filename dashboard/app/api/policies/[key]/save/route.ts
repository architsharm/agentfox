import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const { body, notes, level, scope_id, compose } = await req.json();
  return proxyJson("/api/policies", "POST", {
    body,
    notes: notes || "",
    ...(level ? { level } : {}),
    ...(scope_id ? { scope_id } : {}),
    ...(compose ? { compose } : {}),
  });
}
