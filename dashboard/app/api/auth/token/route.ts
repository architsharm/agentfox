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
 * rather than a broken app.
 *
 * The pasted token is usually the owner's own key, the one the CLI and their app
 * use, so it never becomes the session itself: it is exchanged for a session token
 * of its own (POST /api/tokens, 30 days), and signing out revokes only that (see
 * ../logout/route.ts). A gateway that can't mint one (an older one) gets the pasted
 * token as the session, marked so that signing out never revokes it.
 */

import { NextRequest, NextResponse } from "next/server";
import { apiBase } from "@/lib/env";
import { SESSION_COOKIE } from "@/lib/product/api";
import { KEPT_COOKIE, SIGNED_IN_LANDING } from "@/lib/product/session";
import { requestOrigin } from "@/lib/product/origin";

export const dynamic = "force-dynamic";

const API_BASE = apiBase();

function fail(origin: string, message: string) {
  const url = new URL("/login", origin);
  url.searchParams.set("error", message);
  return NextResponse.redirect(url, 303);
}

export async function POST(req: NextRequest) {
  const origin = requestOrigin(req);
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
  const session = await fetch(`${API_BASE}/api/tokens`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ name: "dashboard sign-in", ttl_days: 30 }),
    cache: "no-store",
  })
    .then(async (r) => (r.ok ? ((await r.json()) as { token?: string }).token : undefined))
    .catch(() => undefined);
  const own = typeof session === "string" && session.startsWith("nom_api_");
  // The one first screen, whatever the way in: Agents, with the setup card when
  // nothing is connected yet.
  const res = NextResponse.redirect(new URL(SIGNED_IN_LANDING, origin), 303);
  const cookie = {
    httpOnly: true,
    // Secure whenever the browser reached us over HTTPS (directly or via a TLS-
    // terminating proxy). Not unconditionally: a compose install on plain
    // http://<lan-ip>:3000 would otherwise never get the cookie back.
    secure:
      req.nextUrl.protocol === "https:" || req.headers.get("x-forwarded-proto") === "https",
    sameSite: "lax" as const,
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  };
  res.cookies.set(SESSION_COOKIE, own ? session : token, cookie);
  if (own) res.cookies.delete(KEPT_COOKIE);
  else res.cookies.set(KEPT_COOKIE, "1", cookie);
  return res;
}
