import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { apiBase } from "@/lib/env";
import { SESSION_COOKIE } from "@/lib/product/api";

export const dynamic = "force-dynamic";

/**
 * Get started, "Send a test request": one real message check through the
 * gateway, as the chosen agent. It is ordinary traffic, not playground, so it
 * shows up where the first request from the agent's own code would.
 *
 * Sent with the key the user just created when there is one (proving the key
 * works), otherwise with their session. Server to server, so the key never has
 * to be allowed through the gateway's CORS policy.
 */
export async function POST(req: NextRequest) {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!session) return NextResponse.json({ ok: false, status: 401, detail: "not signed in" }, { status: 401 });
  const { agent, token } = await req.json().catch(() => ({}));
  if (!agent || typeof agent !== "string") {
    return NextResponse.json({ ok: false, status: 400, detail: "choose an agent" }, { status: 400 });
  }
  const credential = typeof token === "string" && /^nom_(api|agt)_[A-Za-z0-9]+$/.test(token) ? token : session;

  const started = Date.now();
  try {
    const res = await fetch(`${apiBase()}/v1/guard/input`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${credential}` },
      body: JSON.stringify({ agent, content: "Hello from AgentFox setup.", surface: "input" }),
      cache: "no-store",
    });
    const body = await res.json().catch(() => ({}));
    const ms = Date.now() - started;
    if (!res.ok) {
      const detail = typeof body.detail === "string" ? body.detail : res.statusText;
      return NextResponse.json({ ok: false, status: res.status, detail, ms });
    }
    return NextResponse.json({
      ok: true,
      verdict: body.verdict,
      summary: body.explanation?.summary || body.reason || "",
      trace_id: body.trace_id,
      ms,
    });
  } catch (e: any) {
    return NextResponse.json({ ok: false, detail: String(e?.message || e) });
  }
}
