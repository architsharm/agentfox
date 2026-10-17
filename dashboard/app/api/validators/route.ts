import { proxyJson } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/** Every registered validator, its settings schema and whether it runs on this server. */
export async function GET() {
  return proxyJson("/api/validators", "GET");
}
