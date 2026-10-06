import { NextRequest } from "next/server";
import { proxyReviewAction } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

// Folder is `[slug]` to share the path with the sibling owner/boundary routes
// (Next.js requires one dynamic-segment name per path position) — the value that
// actually lands here is the draft agent's *id*, per the caller in agents/page.tsx.
export async function POST(req: NextRequest, { params }: { params: Promise<{ slug: string }> }) {
  const { slug: agentId } = await params;
  return proxyReviewAction(req, `/api/agents/${agentId}/approve`, "/app/agents");
}
