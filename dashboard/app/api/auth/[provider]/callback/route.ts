/**
 * Google / Microsoft OAuth callback. Like the GitHub one, the whole exchange happens
 * here so the session cookie lands on the dashboard's own domain; the gateway is
 * only asked to find-or-create the user (keyed on the provider's subject, never the
 * email) and mint a token.
 */

import { SIGNED_IN_LANDING } from "@/lib/product/session";
import { NextRequest, NextResponse } from "next/server";
import { apiBase, env } from "@/lib/env";
import { SESSION_COOKIE } from "@/lib/product/api";
import { oauthCallbackPath, oauthCredentials, oauthProvider, oauthStateCookie } from "@/lib/product/oauth";

export const dynamic = "force-dynamic";

function fail(origin: string, message: string) {
  const url = new URL("/login", origin);
  url.searchParams.set("error", message);
  return NextResponse.redirect(url);
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ provider: string }> }) {
  const origin = req.nextUrl.origin;
  const { provider: id } = await ctx.params;
  const provider = oauthProvider(id);
  if (!provider) return fail(origin, "Unknown sign-in provider.");

  const code = req.nextUrl.searchParams.get("code");
  const state = req.nextUrl.searchParams.get("state");
  const expected = req.cookies.get(oauthStateCookie(provider.id))?.value;
  if (req.nextUrl.searchParams.get("error")) {
    return fail(origin, `${provider.label} sign-in was cancelled.`);
  }
  if (!code || !state || !expected || state !== expected) {
    return fail(origin, "That sign-in link expired. Please try again.");
  }

  const creds = oauthCredentials(provider);
  const serviceSecret = env("SERVICE_AUTH_SECRET");
  if (!creds || !serviceSecret) return fail(origin, `${provider.label} sign-in is not fully set up on this deployment.`);

  // 1. Code for an access token, straight from the provider over TLS.
  const tokenRes = await fetch(provider.tokenUrl, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
    body: new URLSearchParams({
      client_id: creds.clientId,
      client_secret: creds.clientSecret,
      code,
      grant_type: "authorization_code",
      redirect_uri: new URL(oauthCallbackPath(provider.id), origin).toString(),
    }),
  }).catch(() => null);
  const tokenBody = tokenRes ? await tokenRes.json().catch(() => ({})) : {};
  const accessToken = tokenBody.access_token as string | undefined;
  if (!tokenRes?.ok || !accessToken) {
    return fail(origin, `${provider.label} did not complete the sign-in. Please try again.`);
  }

  // 2. Who is this, from the provider's own userinfo endpoint.
  const infoRes = await fetch(provider.userinfoUrl, {
    headers: { Authorization: `Bearer ${accessToken}` },
  }).catch(() => null);
  const info = infoRes?.ok ? await infoRes.json().catch(() => null) : null;
  if (!info?.sub) return fail(origin, `Could not read your ${provider.label} profile.`);

  // 3. Find-or-create the user and mint a session token.
  const provisionRes = await fetch(`${apiBase()}/api/auth/oauth/provision`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-AgentFox-Service-Secret": serviceSecret },
    body: JSON.stringify({
      provider: provider.id,
      subject: String(info.sub),
      email: info.email_verified === false ? "" : info.email || info.preferred_username || "",
      name: info.name || "",
    }),
  }).catch(() => null);
  if (!provisionRes?.ok) {
    const detail = provisionRes ? (await provisionRes.json().catch(() => ({})))?.detail : null;
    return fail(origin, typeof detail === "string" ? detail : "Could not open your workspace. Please try again.");
  }
  const { token } = await provisionRes.json();

  const res = NextResponse.redirect(new URL(SIGNED_IN_LANDING, origin));
  res.cookies.delete(oauthStateCookie(provider.id));
  res.cookies.set(SESSION_COOKIE, token, {
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 365,
  });
  return res;
}
