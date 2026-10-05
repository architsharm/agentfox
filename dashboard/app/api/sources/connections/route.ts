import { NextRequest } from "next/server";
import { proxyCustomBody } from "@/lib/proxy";
import { connectionBody } from "@/lib/sourceConnection";

/**
 * Connect (or reconnect) an already-registered source. Kept separate from
 * sources/add on purpose: add re-registers the key first, and registration is a
 * full overwrite (tier, owner, domain, freshness), so routing a reconnect through
 * it would reset the source's metadata.
 */
export async function POST(req: NextRequest) {
  const form = await req.formData();
  const key = String(form.get("key") || "").trim();
  const kind = String(form.get("kind") || "").trim();
  return proxyCustomBody(
    req,
    "POST",
    "/api/sources/connections",
    "/app/sources",
    connectionBody(form, key, kind),
    { successNotice: `${key}: connected (${kind})` },
  );
}
