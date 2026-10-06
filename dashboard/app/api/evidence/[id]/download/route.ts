import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";
import { SESSION_COOKIE } from "@/lib/product/api";

const API_BASE = process.env.AGENTFOX_API_URL || process.env.NOMETRIA_API_URL || "http://127.0.0.1:8080";

/**
 * Streams the evidence zip through with the session's auth header. Every other
 * proxy route in this app redirects (form POSTs, no client JS); this one can't —
 * it has to return the binary body itself, since a redirect to the gateway's own
 * URL would leave the browser with no bearer token to attach.
 */
export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) {
    return NextResponse.json({ detail: "not signed in" }, { status: 401 });
  }

  const res = await fetch(`${API_BASE}/api/evidence/${id}/download`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) {
    return NextResponse.json(
      { detail: await res.text().catch(() => res.statusText) },
      { status: res.status },
    );
  }

  return new NextResponse(res.body, {
    status: 200,
    headers: {
      "Content-Type": "application/zip",
      "Content-Disposition":
        res.headers.get("content-disposition") || `attachment; filename="agentfox-evidence-${id}.zip"`,
    },
  });
}
