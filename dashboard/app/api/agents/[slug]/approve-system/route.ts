import { NextRequest } from "next/server";
import { proxyReviewAction } from "@/lib/product/proxy";

export const dynamic = "force-dynamic";

// Adds a proposed agent and every proposed agent it hands work to, in one step: the
// "Add all" button on a multi-agent system in the Proposed list. Like the sibling
// approve route, the value in `[slug]` is the draft agent's *id*.
export async function POST(req: NextRequest, { params }: { params: Promise<{ slug: string }> }) {
  const { slug: agentId } = await params;
  return proxyReviewAction(req, `/api/agents/${agentId}/approve-system`, "/app/agents?tab=proposed");
}
