import { proxyJson } from "@/lib/product/proxy";

/** Add a teammate: `{ email, role }`. The answer holds their sign-in key, shown once. */
export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  return proxyJson("/api/members", "POST", { email: body?.email, role: body?.role });
}
