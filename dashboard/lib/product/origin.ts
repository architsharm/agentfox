import type { NextRequest } from "next/server";

/**
 * The origin the browser actually used, for redirects and same-origin checks.
 *
 * `req.nextUrl.origin` is normalised to the server's own hostname, so a dashboard
 * opened at 127.0.0.1 redirected to localhost after every form post: a different
 * origin, with its own cookies, and a sign-in that seemed not to take. Behind a proxy
 * the forwarded host is the public one.
 */
export function requestOrigin(req: NextRequest): string {
  const host = (req.headers.get("x-forwarded-host") || req.headers.get("host") || "").split(",")[0].trim();
  if (!host) return req.nextUrl.origin;
  const proto = (req.headers.get("x-forwarded-proto") || req.nextUrl.protocol.replace(/:$/, "")).split(",")[0].trim();
  return `${proto}://${host}`;
}
