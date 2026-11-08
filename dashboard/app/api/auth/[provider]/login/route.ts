/**
 * Starts "Continue with Google" or "Continue with Microsoft". Same shape as the
 * GitHub route next door: a double-submit state cookie, then the provider's consent
 * screen. GitHub's own folder is a static segment, so it wins over this one.
 */

import { NextRequest, NextResponse } from "next/server";
import { oauthCallbackPath, oauthCredentials, oauthProvider, oauthStateCookie } from "@/lib/product/oauth";
import { requestOrigin } from "@/lib/product/origin";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest, ctx: { params: Promise<{ provider: string }> }) {
  const { provider: id } = await ctx.params;
  const provider = oauthProvider(id);
  if (!provider) return NextResponse.json({ error: "unknown sign-in provider" }, { status: 404 });

  const creds = oauthCredentials(provider);
  if (!creds) {
    const back = new URL("/login", requestOrigin(req));
    back.searchParams.set("error", `${provider.label} sign-in is not set up on this deployment.`);
    return NextResponse.redirect(back, 303);
  }

  const state = crypto.randomUUID();
  const authorize = new URL(provider.authorizeUrl);
  authorize.searchParams.set("client_id", creds.clientId);
  authorize.searchParams.set("redirect_uri", new URL(oauthCallbackPath(provider.id), req.nextUrl.origin).toString());
  authorize.searchParams.set("response_type", "code");
  authorize.searchParams.set("scope", provider.scope);
  authorize.searchParams.set("state", state);
  if (provider.id === "google") authorize.searchParams.set("prompt", "select_account");

  const res = NextResponse.redirect(authorize);
  res.cookies.set(oauthStateCookie(provider.id), state, {
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: "/",
    maxAge: 600,
  });
  return res;
}
