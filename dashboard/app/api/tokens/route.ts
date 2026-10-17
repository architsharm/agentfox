import { NextRequest } from "next/server";
import { proxyJson } from "@/lib/product/proxy";

/**
 * A raw token is only ever returned once — that has to reach the browser as a
 * value the client component can render and let the user copy, not as a page
 * redirect, since a redirect target has nowhere to carry a secret except the URL
 * (browser history, referrer headers, server logs). Client-driven JSON, same
 * shape as the policy editor's save/validate routes.
 */
export async function GET() {
  return proxyJson("/api/tokens", "GET", undefined, { cache: "no-store" });
}

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  return proxyJson("/api/tokens", "POST", body);
}
