/**
 * Sign in with an API token — the way into a self-hosted dashboard without GitHub.
 *
 * GitHub OAuth is the hosted product's sign-in, and it needs an OAuth app, a public
 * callback URL and a shared service secret. A self-hosted install (docker compose,
 * bare metal) usually has none of those, and the middleware needs a session cookie
 * before any page renders, so before this route such an install had no way in at
 * all. The operator creates themselves and a token on the gateway host:
 *
 *   agentfox admin users create you@example.com --role owner --token
 *
 * and pastes the token on /login. It is checked against the gateway (GET /api/me)
 * before it becomes the session cookie, so a typo is an error on the login page
 * rather than a broken app. The token is the same credential the CLI uses; signing
 * out revokes it (see ../logout/route.ts).
 */

import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE } from "@/lib/api";

export const dynamic = "force-dynamic";

const API_BASE = process.env.AGENTFOX_API_URL || process.env.NOMETRIA_API_URL || "http://127.0.0.1:8080";

function fail(origin: string, message: string) {
  const url = new URL("/login", origin);
  url.searchParams.set("error", message);
  return NextResponse.redirect(url, 303);
}

export async function POST(req: NextRequest) {
  const origin = req.nextUrl.origin;
  // Login CSRF: another site must not be able to sign this browser in as *its*
  // account. A same-origin form post always carries a matching Origin header.
  const sentFrom = req.headers.get("origin");
  if (sentFrom && sentFrom !== origin) {
    return fail(origin, "sign-in must be submitted from this site");
  }
  const form = await req.formData();
  const token = String(form.get("token") || "").trim();
  if (!token.startsWith("nom_api_")) {
    return fail(origin, "paste an operator API token (it starts with nom_api_)");
  }
  let ok = false;
  try {
    const res = await fetch(`${API_BASE}/api/me`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
    ok = res.ok;
  } catch {
    return fail(origin, "could not reach the control plane to check that token");
  }
  if (!ok) {
    return fail(origin, "that token is invalid, expired or revoked");
  }
  const res = NextResponse.redirect(new URL("/app/start", origin), 303);
  res.cookies.set(SESSION_COOKIE, token, {
    httpOnly: true,
    // Secure whenever the browser reached us over HTTPS (directly or via a TLS-
    // terminating proxy). Not unconditionally: a compose install on plain
    // http://<lan-ip>:3000 would otherwise never get the cookie back.
    secure:
      req.nextUrl.protocol === "https:" || req.headers.get("x-forwarded-proto") === "https",
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
  return res;
}
