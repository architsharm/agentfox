import { NextRequest } from "next/server";
import { proxyFormPost } from "@/lib/proxy";

export const dynamic = "force-dynamic";

/**
 * The CLI (`agentfox test redteam <agent>`) was the only way to trigger this —
 * fine for someone who has the repo checked out, a dead end for anyone using
 * only the dashboard. Runs synchronously and redirects back with the result.
 */
export async function POST(req: NextRequest) {
  return proxyFormPost(req, "/api/redteam/campaigns", "/app/evals");
}
