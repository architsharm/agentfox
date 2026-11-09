import { NextRequest, NextResponse } from "next/server";
import { apiBase } from "@/lib/env";
import { SESSION_COOKIE } from "@/lib/product/api";
import { KEPT_COOKIE } from "@/lib/product/session";
import { requestOrigin } from "@/lib/product/origin";

export const dynamic = "force-dynamic";

const API_BASE = apiBase();

/**
 * Sign Out ends the session's token, not just the cookie that carries it. That
 * token is one minted for this browser at sign-in (GitHub, another provider, or in
 * exchange for a pasted key), never the pasted key itself.
 *
 * Deleting the cookie alone left the token valid at the gateway for the rest of its
 * life (a GitHub sign-in token lasts 365 days), so a copied cookie outlived the
 * sign-out. The gateway's POST /api/auth/logout revokes exactly the token presented.
 * A gateway that is down or refuses must not trap someone signed in, so the cookie
 * is deleted whatever the revoke returns.
 */
export async function POST(req: NextRequest) {
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  // A pasted key kept as the session (an older gateway could not mint one): the
  // browser signs out, the key the CLI and the app use keeps working.
  const kept = req.cookies.get(KEPT_COOKIE)?.value === "1";
  if (token && !kept) {
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
  const res = NextResponse.redirect(new URL("/login", requestOrigin(req)), 303);
  res.cookies.delete(SESSION_COOKIE);
  res.cookies.delete(KEPT_COOKIE);
  return res;
}
