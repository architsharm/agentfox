/**
 * GitHub OAuth callback — the one place this app talks to GitHub directly.
 *
 * Cookies set here live on the dashboard's own domain. The gateway runs as a
 * separate Vercel project on a separate *.vercel.app domain, so a cookie it set
 * would never reach this one — there is no shared parent domain to scope it to.
 * That's why the whole OAuth dance (redirect, code exchange, token) happens here in
 * Next.js rather than in the gateway: only the dashboard can set a cookie the
 * dashboard's own pages will see. Everything server-to-server after that (minting a
 * agentfox token, storing the GitHub access token) still goes through the gateway,
 * which stays the only thing that reads or writes the database.
 */

import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE } from "@/lib/api";

export const dynamic = "force-dynamic";

const STATE_COOKIE = "gh_oauth_state";
const API_BASE = process.env.AGENTFOX_API_URL || process.env.NOMETRIA_API_URL || "http://127.0.0.1:8080";

function fail(origin: string, message: string) {
  const url = new URL("/login", origin);
  url.searchParams.set("error", message);
  return NextResponse.redirect(url);
}

export async function GET(req: NextRequest) {
  const origin = req.nextUrl.origin;
  const code = req.nextUrl.searchParams.get("code");
  const state = req.nextUrl.searchParams.get("state");
  const expectedState = req.cookies.get(STATE_COOKIE)?.value;

  if (!code || !state || !expectedState || state !== expectedState) {
    return fail(origin, "invalid or expired sign-in attempt — please try again");
  }

  const clientId = process.env.GITHUB_CLIENT_ID;
  const clientSecret = process.env.GITHUB_CLIENT_SECRET;
  const serviceSecret = process.env.AGENTFOX_SERVICE_AUTH_SECRET || process.env.NOMETRIA_SERVICE_AUTH_SECRET;
  if (!clientId || !clientSecret || !serviceSecret) {
    return fail(origin, "GitHub sign-in is not fully configured on this deployment");
  }

  // 1. Exchange the code for a GitHub access token.
  const tokenRes = await fetch("https://github.com/login/oauth/access_token", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      client_id: clientId,
      client_secret: clientSecret,
      code,
      redirect_uri: new URL("/api/auth/github/callback", origin).toString(),
    }),
  });
  const tokenBody = await tokenRes.json();
  const githubToken = tokenBody.access_token as string | undefined;
  if (!tokenRes.ok || !githubToken) {
    return fail(origin, tokenBody.error_description || "GitHub token exchange failed");
  }

  // 2. Who is this? Email may be private, so fall back to the emails endpoint.
  const [profileRes, emailsRes] = await Promise.all([
    fetch("https://api.github.com/user", {
      headers: { Authorization: `Bearer ${githubToken}`, Accept: "application/vnd.github+json" },
    }),
    fetch("https://api.github.com/user/emails", {
      headers: { Authorization: `Bearer ${githubToken}`, Accept: "application/vnd.github+json" },
    }),
  ]);
  if (!profileRes.ok) return fail(origin, "could not read the GitHub profile");
  const profile = await profileRes.json();
  let email: string | null = profile.email ?? null;
  if (!email && emailsRes.ok) {
    const emails = await emailsRes.json();
    email = emails.find((e: any) => e.primary)?.email ?? emails[0]?.email ?? null;
  }

  // 3. Find-or-create the user + org, and mint a real agentfox token — the one
  // privileged call, authenticated with a shared secret rather than a user token
  // because no user token exists yet at this point.
  const provisionRes = await fetch(`${API_BASE}/api/auth/github/provision`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Nometria-Service-Secret": serviceSecret },
    body: JSON.stringify({
      github_user_id: String(profile.id),
      github_login: profile.login,
      email: email || `${profile.login}@users.noreply.github.com`,
      name: profile.name || profile.login,
    }),
  });
  if (!provisionRes.ok) {
    return fail(origin, "could not provision an account for this GitHub identity");
  }
  const { token } = await provisionRes.json();

  // 4. Store the GitHub access token itself, so the gateway can list/scan repos
  // later without asking GitHub to authenticate this person again.
  await fetch(`${API_BASE}/api/integrations/github/connect`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ access_token: githubToken }),
  });

  const res = NextResponse.redirect(new URL("/app/start?tab=connect", origin));
  res.cookies.delete(STATE_COOKIE);
  res.cookies.set(SESSION_COOKIE, token, {
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 365,
  });
  return res;
}
