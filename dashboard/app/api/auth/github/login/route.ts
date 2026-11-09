/**
 * Starts "Sign in with GitHub". This is the whole login flow — there is no
 * separate signup and no password — and it doubles as the repo-connection grant:
 * the same OAuth scope that proves who someone is also lets the callback hand the
 * gateway a token it can list and scan repos with (see routes/integrations.py).
 */

import { NextRequest, NextResponse } from "next/server";
import { requestOrigin } from "@/lib/product/origin";

export const dynamic = "force-dynamic";

const STATE_COOKIE = "gh_oauth_state";

const NOT_CONFIGURED = "GitHub sign-in is not configured (GITHUB_CLIENT_ID is unset).";

export async function GET(req: NextRequest) {
  const clientId = process.env.GITHUB_CLIENT_ID;
  if (!clientId) {
    // A browser following a "Connect GitHub" button gets a page, not raw JSON: back
    // to sign-in with the reason, or to Connections, whose GitHub card says it is
    // not configured. A script (curl, the docs) still gets the 503.
    if (!(req.headers.get("accept") || "").includes("text/html")) {
      return NextResponse.json({ error: NOT_CONFIGURED }, { status: 503 });
    }
    const origin = requestOrigin(req);
    let from = "";
    try {
      const ref = new URL(req.headers.get("referer") || "");
      if (ref.origin === origin) from = ref.pathname;
    } catch {
      // No referrer, or not a URL: Connections.
    }
    const back = from === "/login" ? new URL("/login", origin) : new URL("/app/start?tab=connect", origin);
    if (from === "/login") back.searchParams.set("error", NOT_CONFIGURED);
    return NextResponse.redirect(back, 303);
  }

  // Double-submit-cookie CSRF check: a value we set here as a cookie and also pass
  // as `state`, verified to match by the callback. No separate signing secret needed.
  const state = crypto.randomUUID();
  const callbackUrl = new URL("/api/auth/github/callback", req.nextUrl.origin);
  const authorizeUrl = new URL("https://github.com/login/oauth/authorize");
  authorizeUrl.searchParams.set("client_id", clientId);
  authorizeUrl.searchParams.set("redirect_uri", callbackUrl.toString());
  // Only what is used: `repo` to list and scan repositories (private ones too),
  // `user:email` for the address when it is private. The public profile the callback
  // reads (`GET /user`) needs no scope, so `read:user` is not requested.
  authorizeUrl.searchParams.set("scope", "repo user:email");
  authorizeUrl.searchParams.set("state", state);

  const res = NextResponse.redirect(authorizeUrl);
  res.cookies.set(STATE_COOKIE, state, {
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: "/",
    maxAge: 600,
  });
  return res;
}
