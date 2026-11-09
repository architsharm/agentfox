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
  const proto = (req.headers.get("x-forwarded-proto") || req.nextUrl.protocol.replace(/:$/, "")).split(",")[0].trim();
  const origin = host ? `${proto}://${host}` : req.nextUrl.origin;
  // Host and X-Forwarded-Host are whatever the client sent unless a proxy rewrites
  // them. A deployment that lists its origins in AGENTFOX_ALLOWED_ORIGINS never
  // builds a redirect from any other: an unlisted host gets the first listed one.
  const allowed = allowedOrigins();
  if (allowed.length && !allowed.includes(origin)) return allowed[0];
  return origin;
}

/** `AGENTFOX_ALLOWED_ORIGINS`, comma-separated, without trailing slashes. Empty when unset. */
export function allowedOrigins(): string[] {
  return (process.env.AGENTFOX_ALLOWED_ORIGINS || "")
    .split(",")
    .map((o) => o.trim().replace(/\/+$/, ""))
    .filter(Boolean);
}
