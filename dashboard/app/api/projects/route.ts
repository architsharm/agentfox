import { proxyJson } from "@/lib/product/proxy";

/** Every project (a repository `agentfox init` mapped). Setup reads it to open the new one. */
export async function GET() {
  return proxyJson("/api/projects", "GET", undefined, { cache: "no-store" });
}
