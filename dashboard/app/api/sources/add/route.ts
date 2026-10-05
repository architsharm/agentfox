import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";
import { SESSION_COOKIE } from "@/lib/api";
import { connectionBody } from "@/lib/sourceConnection";

const API_BASE = process.env.AGENTFOX_API_URL || process.env.NOMETRIA_API_URL || "http://127.0.0.1:8080";

/**
 * The single-flow "add a source" form posts here instead of chaining a plain
 * `/api/sources` PUT and a `/api/sources/connections` POST from two separate
 * cards — a connection can only attach to an already-registered key
 * (`register_connection` 400s otherwise), so registering first and connecting
 * second, in one request, is what lets the form read as "add a source" rather
 * than "do step 1, then remember to also do step 2".
 */
export async function POST(req: NextRequest) {
  const target = new URL("/app/sources", req.nextUrl.origin);
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) {
    target.searchParams.set("review_error", "not signed in");
    return NextResponse.redirect(target);
  }

  const form = await req.formData();
  const str = (name: string) => String(form.get(name) || "").trim();
  const type = str("source_type") || "register";
  const key = str("key");

  const registerBody: Record<string, unknown> = { key };
  const tier = str("tier");
  if (tier) registerBody.tier = tier;
  const owner = str("owner");
  if (owner) registerBody.owner = owner;
  const freshness = str("freshness_sla_hours");
  if (freshness) registerBody.freshness_sla_hours = Number(freshness);

  try {
    const registerRes = await fetch(`${API_BASE}/api/sources`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify(registerBody),
    });
    if (!registerRes.ok) {
      const body = await registerRes.json().catch(() => ({}));
      target.searchParams.set("review_error", body.detail || registerRes.statusText);
      return NextResponse.redirect(target);
    }

    if (type !== "database" && type !== "api") {
      target.searchParams.set("review_notice", `${key}: added`);
      return NextResponse.redirect(target);
    }

    const connection = connectionBody(form, key, type);

    const connectionRes = await fetch(`${API_BASE}/api/sources/connections`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify(connection),
    });
    if (!connectionRes.ok) {
      const body = await connectionRes.json().catch(() => ({}));
      target.searchParams.set(
        "review_error",
        `${key}: registered, but the connection failed — ${body.detail || connectionRes.statusText}. Edit it below to try again.`,
      );
      return NextResponse.redirect(target);
    }
    target.searchParams.set("review_notice", `${key}: added and connected (${type})`);
  } catch (e: any) {
    target.searchParams.set("review_error", String(e?.message || e));
  }
  return NextResponse.redirect(target);
}
