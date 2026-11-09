import { NextRequest, NextResponse } from "next/server";
import { apiBase } from "@/lib/env";
import { SESSION_COOKIE } from "@/lib/product/api";
import { detailText } from "@/lib/product/errors";
import { requestOrigin } from "@/lib/product/origin";
import { MAP_PROJECT_COOKIE, PROJECT_COOKIE } from "@/lib/product/project";

export const dynamic = "force-dynamic";

const BACK = "/app/settings?tab=retention";
/** NewProjectGate's SKIP_COOKIE; that module is a client component, so not imported here. */
const SETUP_SKIPPED_COOKIE = "agentfox_setup_skipped";

/**
 * "Delete my account" in Settings, Retention. A plain form post carrying the email
 * the owner typed back; the gateway (POST /api/account/delete) decides whether the
 * workspace may go and deletes it. On success the session is already dead at the
 * gateway (its token was a row in the workspace), so the browser's cookies go too
 * and the person lands on /login with a sentence saying it is done. On refusal
 * they go back to Settings with the gateway's reason, still signed in.
 */
export async function POST(req: NextRequest) {
  const origin = requestOrigin(req);
  const back = new URL(BACK, origin);
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  if (!token) {
    back.searchParams.set("review_error", "not signed in");
    return NextResponse.redirect(back, 303);
  }
  const form = await req.formData().catch(() => null);
  const confirm = form?.get("confirm");
  try {
    const res = await fetch(`${apiBase()}/api/account/delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ confirm: typeof confirm === "string" ? confirm : "" }),
      cache: "no-store",
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      back.searchParams.set("review_error", detailText(body?.detail) || "Could not delete the account.");
      return NextResponse.redirect(back, 303);
    }
  } catch {
    back.searchParams.set("review_error", "Could not reach the server. Nothing was deleted.");
    return NextResponse.redirect(back, 303);
  }
  const done = NextResponse.redirect(new URL("/login?deleted=1", origin), 303);
  for (const name of [SESSION_COOKIE, PROJECT_COOKIE, MAP_PROJECT_COOKIE, SETUP_SKIPPED_COOKIE]) {
    done.cookies.delete(name);
  }
  return done;
}
