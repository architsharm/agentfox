import { NextRequest } from "next/server";
import { proxyFormPost } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

/**
 * Manual registration — the counterpart to the repo-scan draft flow. A team
 * whose agent doesn't live in a scanned repo (or hasn't connected one yet) had
 * no way onto this page at all otherwise.
 */
export async function POST(req: NextRequest) {
  return proxyFormPost(req, "/api/agents", "/app/agents");
}
