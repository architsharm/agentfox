import { NextRequest, NextResponse } from "next/server";
import { apiBase } from "@/lib/env";
import { SESSION_COOKIE } from "@/lib/product/api";

export const dynamic = "force-dynamic";

const API_BASE = apiBase();

/**
 * Sign Out ends the session's token, not just the cookie that carries it.
 *
 * Deleting the cookie alone left the token valid at the gateway for the rest of its
 * life (a GitHub sign-in token lasts 365 days), so a copied cookie outlived the
 * sign-out. The gateway's POST /api/auth/logout revokes exactly the token presented.
 * A gateway that is down or refuses must not trap someone signed in, so the cookie
 * is deleted whatever the revoke returns.
 */
export async function POST(req: NextRequest) {
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  if (token) {
    try {
      await fetch(`${API_BASE}/api/auth/logout`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
      });
    } catch {
      // Unreachable gateway: still sign the browser out (see above).
    }
  }
  const res = NextResponse.redirect(new URL("/login", req.nextUrl.origin), 303);
  res.cookies.delete(SESSION_COOKIE);
  return res;
}
